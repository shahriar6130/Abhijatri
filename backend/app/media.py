"""Photos and videos on member reviews (Review.md 8; amendment A4 approved without transcoding, 27 Oct 2026).

Flow: the author asks for an upload intent, the browser PUTs the file to a one-time signed Storage
URL under `quarantine/`, then calls `complete`. Only then does the server read the object:

- images: the real format is read from the bytes (the browser's type is not trusted), the pixel count
  is checked before decoding, and the picture is re-encoded to WebP with no EXIF/GPS metadata;
- videos: the MP4 structure is parsed (H.264 video, AAC audio, at most 60 s); metadata boxes and
  non-audio/video tracks are overwritten in place as `free` boxes, which strips location and device
  data without transcoding and without moving any byte offsets.

The checked copy goes to `processed/`; the quarantine object is deleted. A moderator approves or
rejects media with the review decision, and only approved media of a published review are shown.
"""

import io
import logging
import struct
import tempfile
import uuid
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import IO, Any

from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.sessions import Principal
from app.errors import ApiError
from app.models import ModerationDecision, Review, ReviewMedia, ReviewStatus
from app.storage import MEDIA_BUCKET, StorageClient, StorageUnavailable

logger = logging.getLogger(__name__)

MAX_IMAGES = 5
MAX_VIDEOS = 1
IMAGE_MAX_BYTES = 8 * 1024 * 1024
VIDEO_MAX_BYTES = 50 * 1024 * 1024
IMAGE_MAX_PIXELS = 20_000_000
VIDEO_MAX_MS = 60_000
VIDEO_DURATION_GRACE_MS = 500  # encoders round the last frame
IMAGE_TYPES = ("image/jpeg", "image/png", "image/webp")
VIDEO_TYPES = ("video/mp4",)
PROCESSED_LONG_EDGE = 2048
PUBLIC_URL_SECONDS = 3600
STAFF_URL_SECONDS = 300
ABANDONED_AFTER = timedelta(hours=24)
LIVE_STATES = ("awaiting_upload", "pending", "approved")


class MediaRejected(Exception):
    """The uploaded file failed a server check. ``code`` is the field error code shown to the author."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _invalid(field: str, code: str) -> ApiError:
    return ApiError("VALIDATION_FAILED", field_errors=[{"field": field, "code": code}])


# ---- images ----


def process_image(data: bytes) -> tuple[bytes, int, int]:
    """Return the re-encoded WebP bytes and their size. Raises ``MediaRejected``."""
    try:
        with Image.open(io.BytesIO(data)) as probe:
            if probe.format not in ("JPEG", "PNG", "WEBP"):
                raise MediaRejected("TYPE")
            width, height = probe.size
            if width * height > IMAGE_MAX_PIXELS:
                raise MediaRejected("TOO_MANY_PIXELS")
            probe.load()
            picture = ImageOps.exif_transpose(probe)  # keep the orientation the camera meant, then drop EXIF
    except MediaRejected:
        raise
    except (UnidentifiedImageError, OSError, ValueError, Image.DecompressionBombError) as error:
        raise MediaRejected("BROKEN") from error
    if picture.mode not in ("RGB", "RGBA"):
        picture = picture.convert("RGBA" if "A" in picture.getbands() else "RGB")
    picture.thumbnail((PROCESSED_LONG_EDGE, PROCESSED_LONG_EDGE))
    out = io.BytesIO()
    picture.save(out, format="WEBP", quality=85, method=4)  # no exif/icc/xmp arguments: nothing carried over
    return out.getvalue(), picture.width, picture.height


# ---- videos (ISO base media / MP4) ----

_MP4_BRANDS = {b"isom", b"iso2", b"iso4", b"iso5", b"iso6", b"mp41", b"mp42", b"avc1", b"M4V ", b"MSNV", b"dash"}
_KEEP_TOP = {b"ftyp", b"moov", b"mdat", b"free", b"skip", b"wide"}
_STRIP_IN_MOOV = {b"udta", b"meta", b"uuid"}
_VIDEO_CODECS = {b"avc1", b"avc3"}
_AUDIO_CODECS = {b"mp4a"}
_MAX_MOOV_BYTES = 16 * 1024 * 1024


@dataclass
class _Box:
    kind: bytes
    start: int
    body: int
    end: int


def _boxes(f: IO[bytes], start: int, end: int) -> Iterator[_Box]:
    position = start
    while position + 8 <= end:
        f.seek(position)
        size, kind = struct.unpack(">I4s", f.read(8))
        header = 8
        if size == 1:
            size = struct.unpack(">Q", f.read(8))[0]
            header = 16
        elif size == 0:
            size = end - position
        if size < header or position + size > end:
            raise MediaRejected("BROKEN")
        yield _Box(kind, position, position + header, position + size)
        position += size


def _child(f: IO[bytes], box: _Box, kind: bytes) -> _Box | None:
    return next((b for b in _boxes(f, box.body, box.end) if b.kind == kind), None)


def _neutralise(f: IO[bytes], box: _Box) -> None:
    """Turn a box into a `free` box of the same size and blank its contents (offsets stay valid)."""
    f.seek(box.start + 4)
    f.write(b"free")
    f.seek(box.body)
    remaining = box.end - box.body
    while remaining > 0:
        step = min(remaining, 64 * 1024)
        f.write(b"\0" * step)
        remaining -= step


def _read(f: IO[bytes], at: int, size: int) -> bytes:
    f.seek(at)
    data = f.read(size)
    if len(data) != size:
        raise MediaRejected("BROKEN")
    return data


def check_and_strip_video(f: IO[bytes], length: int) -> tuple[int, int | None, int | None]:
    """Validate an MP4 in ``f`` (opened read/write) and strip its metadata in place.

    Returns (duration in ms, width, height). Raises ``MediaRejected``.
    """
    boxes = _boxes(f, 0, length)
    first = next(boxes, None)
    if first is None or first.kind != b"ftyp":
        raise MediaRejected("TYPE")  # not an MP4 at all, whatever the browser said
    top = [first, *boxes]
    ftyp = _read(f, top[0].body, top[0].end - top[0].body)
    brands = {ftyp[0:4]} | {ftyp[i : i + 4] for i in range(8, len(ftyp) - 3, 4)}
    if not brands & _MP4_BRANDS:
        raise MediaRejected("TYPE")
    moov = next((b for b in top if b.kind == b"moov"), None)
    if moov is None or not any(b.kind == b"mdat" for b in top) or moov.end - moov.start > _MAX_MOOV_BYTES:
        raise MediaRejected("BROKEN")

    mvhd = _child(f, moov, b"mvhd")
    if mvhd is None:
        raise MediaRejected("BROKEN")
    version = _read(f, mvhd.body, 1)[0]
    if version == 1:
        timescale, duration = struct.unpack(">IQ", _read(f, mvhd.body + 20, 12))
    else:
        timescale, duration = struct.unpack(">II", _read(f, mvhd.body + 12, 8))
    if timescale == 0:
        raise MediaRejected("BROKEN")
    duration_ms = duration * 1000 // timescale
    if duration_ms > VIDEO_MAX_MS + VIDEO_DURATION_GRACE_MS:
        raise MediaRejected("TOO_LONG")

    width = height = None
    video_tracks = 0
    for box in list(_boxes(f, moov.body, moov.end)):
        if box.kind in _STRIP_IN_MOOV:
            _neutralise(f, box)
            continue
        if box.kind != b"trak":
            continue
        mdia = _child(f, box, b"mdia")
        hdlr = _child(f, mdia, b"hdlr") if mdia else None
        handler = _read(f, hdlr.body + 8, 4) if hdlr else b""
        if handler not in (b"vide", b"soun"):
            _neutralise(f, box)  # timed metadata, timecode, chapters: not needed to play, may hold location
            continue
        minf = _child(f, mdia, b"minf") if mdia else None
        stbl = _child(f, minf, b"stbl") if minf else None
        stsd = _child(f, stbl, b"stsd") if stbl else None
        if stsd is None:
            raise MediaRejected("BROKEN")
        codec = _read(f, stsd.body + 12, 4)  # version/flags, entry count, first entry size, then its type
        if handler == b"vide":
            if codec not in _VIDEO_CODECS:
                raise MediaRejected("VIDEO_CODEC")
            video_tracks += 1
            tkhd = _child(f, box, b"tkhd")
            if tkhd is not None:
                offset = 88 if _read(f, tkhd.body, 1)[0] == 1 else 76
                w, h = struct.unpack(">II", _read(f, tkhd.body + offset, 8))
                width, height = w >> 16, h >> 16
        elif codec not in _AUDIO_CODECS:
            raise MediaRejected("VIDEO_CODEC")
        for inner in list(_boxes(f, box.body, box.end)):
            if inner.kind in _STRIP_IN_MOOV:
                _neutralise(f, inner)
    if video_tracks != 1:
        raise MediaRejected("BROKEN")
    for box in top:
        if box.kind not in _KEEP_TOP:
            _neutralise(f, box)
    return int(duration_ms), width, height


# ---- service ----


def _kind(content_type: str) -> str:
    if content_type in IMAGE_TYPES:
        return "image"
    if content_type in VIDEO_TYPES:
        return "video"
    raise _invalid("content_type", "TYPE")


def _own_pending_review(session: Session, principal: Principal, review_id: uuid.UUID) -> Review:
    review = session.scalar(select(Review).where(Review.id == review_id).with_for_update())
    if review is None or review.author_user_id != principal.user.id:
        raise ApiError("NOT_FOUND")  # another person's review is not disclosed
    if review.status not in (ReviewStatus.PENDING, ReviewStatus.CHANGES_REQUESTED):
        raise ApiError("TRANSITION_NOT_ALLOWED")  # media can be added only before the moderator decides
    return review


def create_intent(
    session: Session,
    storage: StorageClient,
    principal: Principal,
    review_id: uuid.UUID,
    *,
    content_type: str,
    size_bytes: int,
    alt_text: str,
    caption: str | None,
) -> dict[str, Any]:
    review = _own_pending_review(session, principal, review_id)
    kind = _kind(content_type)
    limit_bytes = IMAGE_MAX_BYTES if kind == "image" else VIDEO_MAX_BYTES
    if size_bytes > limit_bytes:
        raise _invalid("size_bytes", "TOO_LARGE")
    counts = dict(
        session.execute(
            select(ReviewMedia.kind, func.count())
            .where(ReviewMedia.review_id == review.id, ReviewMedia.state.in_(LIVE_STATES))
            .group_by(ReviewMedia.kind)
        ).all()
    )
    if counts.get(kind, 0) >= (MAX_IMAGES if kind == "image" else MAX_VIDEOS):
        raise _invalid("content_type", "TOO_MANY")
    position = session.scalar(select(func.count()).select_from(ReviewMedia).where(ReviewMedia.review_id == review.id)) or 0
    media_id = uuid.uuid4()
    media = ReviewMedia(
        id=media_id,
        review_id=review.id,
        uploader_id=principal.user.id,
        kind=kind,
        position=position,
        content_type=content_type,
        quarantine_key=f"quarantine/{review.id}/{media_id}",
        alt_text=alt_text,
        caption=caption,
        ownership_declared=True,
    )
    session.add(media)
    session.flush()
    upload_url = storage.signed_upload_url(media.quarantine_key, MEDIA_BUCKET)
    return {"media_id": str(media.id), "kind": kind, "upload_url": upload_url, "max_bytes": limit_bytes}


def complete_upload(session: Session, storage: StorageClient, principal: Principal, review_id: uuid.UUID, media_id: uuid.UUID) -> ReviewMedia:
    """Check and process the uploaded object. On a bad file the row is marked `removed` and
    ``MediaRejected`` is raised; the caller commits that state before answering."""
    _own_pending_review(session, principal, review_id)
    media = session.scalar(select(ReviewMedia).where(ReviewMedia.id == media_id, ReviewMedia.review_id == review_id).with_for_update())
    if media is None or media.state == "removed":
        raise ApiError("NOT_FOUND")
    if media.state != "awaiting_upload":
        return media  # a retry after a lost response
    if not storage.exists(media.quarantine_key, MEDIA_BUCKET):
        raise _invalid("file", "NOT_UPLOADED")
    limit_bytes = IMAGE_MAX_BYTES if media.kind == "image" else VIDEO_MAX_BYTES
    width: int | None
    height: int | None
    duration_ms: int | None = None
    with tempfile.SpooledTemporaryFile(max_size=IMAGE_MAX_BYTES + 1) as spool:
        try:
            size = storage.download(media.quarantine_key, spool, MEDIA_BUCKET, limit_bytes)
            if media.kind == "image":
                spool.seek(0)
                processed, width, height = process_image(spool.read())
                content_type, extension = "image/webp", "webp"
                body = processed
                size = len(processed)
            else:
                duration_ms, width, height = check_and_strip_video(spool, size)
                spool.seek(0)
                content_type, extension, body = "video/mp4", "mp4", spool.read()  # a known length for Storage
        except ValueError:
            _reject(storage, media)
            raise MediaRejected("TOO_LARGE") from None
        except MediaRejected:
            _reject(storage, media)
            raise
        processed_key = f"processed/{review_id}/{media.id}.{extension}"
        storage.upload(processed_key, body, content_type, MEDIA_BUCKET)
    _delete_quietly(storage, [media.quarantine_key])
    media.processed_key = processed_key
    media.content_type = content_type
    media.size_bytes, media.width, media.height, media.duration_ms = size, width, height, duration_ms
    media.state = "pending"
    media.uploaded_at = datetime.now(UTC)
    return media


def _reject(storage: StorageClient, media: ReviewMedia) -> None:
    media.state = "removed"
    _delete_quietly(storage, [media.quarantine_key])


def _delete_quietly(storage: StorageClient, keys: list[str]) -> None:
    try:
        storage.delete(keys, MEDIA_BUCKET)
    except StorageUnavailable:
        logger.warning("media object not deleted now; the retention job retries")


def remove(session: Session, storage: StorageClient, principal: Principal, review_id: uuid.UUID, media_id: uuid.UUID) -> None:
    """The author takes a photo or video off their review before moderation."""
    _own_pending_review(session, principal, review_id)
    media = session.scalar(select(ReviewMedia).where(ReviewMedia.id == media_id, ReviewMedia.review_id == review_id).with_for_update())
    if media is None or media.state == "removed":
        raise ApiError("NOT_FOUND")
    keys = [k for k in (media.quarantine_key, media.processed_key) if k]
    media.state = "removed"
    _delete_quietly(storage, keys)


def apply_decision(
    session: Session, review_id: uuid.UUID, decision: ModerationDecision, actor_id: uuid.UUID, rejected_ids: set[uuid.UUID]
) -> dict[str, list[str]]:
    """Decide the review's checked media together with the review (same transaction)."""
    media = list(session.scalars(select(ReviewMedia).where(ReviewMedia.review_id == review_id, ReviewMedia.state == "pending").with_for_update()))
    unknown = rejected_ids - {m.id for m in media}
    if unknown or (rejected_ids and decision != ModerationDecision.PUBLISH):
        raise ApiError("VALIDATION_FAILED", field_errors=[{"field": "rejected_media_ids", "code": "INVALID_VALUE"}])
    outcome: dict[str, list[str]] = {"approved": [], "rejected": []}
    if decision not in (ModerationDecision.PUBLISH, ModerationDecision.REJECT):
        return outcome
    now = datetime.now(UTC)
    for item in media:
        approved = decision == ModerationDecision.PUBLISH and item.id not in rejected_ids
        item.state = "approved" if approved else "rejected"
        item.decided_by, item.decided_at = actor_id, now
        outcome["approved" if approved else "rejected"].append(str(item.id))
    return outcome


def change_decision(session: Session, media_id: uuid.UUID, approve: bool, actor_id: uuid.UUID) -> tuple[ReviewMedia, str]:
    """Correct a photo or video decision after the review was decided. Returns the item and its old state.

    Pending items are decided with their review (the queue); removed or unprocessed items cannot be shown."""
    item = session.scalar(select(ReviewMedia).where(ReviewMedia.id == media_id).with_for_update())
    if item is None:
        raise ApiError("NOT_FOUND")
    if item.state not in ("approved", "rejected") or item.processed_key is None:
        raise ApiError("TRANSITION_NOT_ALLOWED")
    previous = item.state
    item.state = "approved" if approve else "rejected"
    item.decided_by, item.decided_at = actor_id, datetime.now(UTC)
    return item, previous


def staff_list(session: Session, state: str | None, limit: int) -> list[dict[str, Any]]:
    """Decided and pending media, newest first, with the review they belong to."""
    statement = (
        select(ReviewMedia, Review.status, Review.destination_id)
        .join(Review, Review.id == ReviewMedia.review_id)
        .where(ReviewMedia.state.in_(("pending", "approved", "rejected")))
        .order_by(ReviewMedia.created_at.desc())
        .limit(limit)
    )
    if state:
        statement = statement.where(ReviewMedia.state == state)
    return [
        describe(item) | {"review_id": str(item.review_id), "review_status": status.value, "destination_id": str(destination_id), "decided_at": item.decided_at.isoformat() if item.decided_at else None}
        for item, status, destination_id in session.execute(statement).all()
    ]


def describe(item: ReviewMedia, url: str | None = None) -> dict[str, Any]:
    return {
        "id": str(item.id),
        "kind": item.kind,
        "state": item.state,
        "content_type": item.content_type,
        "alt_text": item.alt_text,
        "caption": item.caption,
        "width": item.width,
        "height": item.height,
        "duration_ms": item.duration_ms,
        "size_bytes": item.size_bytes,
        "url": url,
    }


def published_media(session: Session, storage: StorageClient, review_ids: list[uuid.UUID]) -> dict[uuid.UUID, list[dict[str, Any]]]:
    """Approved media of the given reviews, each with a signed link valid for an hour.

    A Storage failure leaves the media out rather than failing the public review feed."""
    if not review_ids:
        return {}
    rows = list(
        session.scalars(
            select(ReviewMedia)
            .where(ReviewMedia.review_id.in_(review_ids), ReviewMedia.state == "approved")
            .order_by(ReviewMedia.review_id, ReviewMedia.position)
        )
    )
    if not rows:
        return {}
    try:
        urls = storage.signed_download_urls([r.processed_key for r in rows if r.processed_key], MEDIA_BUCKET, PUBLIC_URL_SECONDS)
    except StorageUnavailable:
        logger.warning("review media links unavailable; the feed is served without them")
        return {}
    grouped: dict[uuid.UUID, list[dict[str, Any]]] = {}
    for row in rows:
        url = urls.get(row.processed_key or "")
        if url:
            grouped.setdefault(row.review_id, []).append(describe(row, url))
    return grouped


def staff_url(session: Session, storage: StorageClient, review_id: uuid.UUID, media_id: uuid.UUID) -> str:
    media = session.scalar(select(ReviewMedia).where(ReviewMedia.id == media_id, ReviewMedia.review_id == review_id))
    if media is None or media.processed_key is None or media.state == "removed":
        raise ApiError("NOT_FOUND")
    return storage.signed_download_url(media.processed_key, MEDIA_BUCKET, STAFF_URL_SECONDS)


def purge_abandoned(session: Session, storage: StorageClient, now: datetime) -> int:
    """Delete uploads never completed within 24 hours (Review.md 8). Returns the number purged."""
    stale = list(
        session.scalars(
            select(ReviewMedia)
            .where(ReviewMedia.state == "awaiting_upload", ReviewMedia.created_at < now - ABANDONED_AFTER)
            .with_for_update(skip_locked=True)
        )
    )
    if not stale:
        return 0
    storage.delete([m.quarantine_key for m in stale], MEDIA_BUCKET)
    for item in stale:
        session.delete(item)
    return len(stale)
