"""Member reviews with photos and videos (Review.md 3.3 and 8; amendment A4 without transcoding)."""

import io
import struct
import tempfile
import uuid
from datetime import UTC, date, datetime, timedelta
from typing import IO, Any

import pytest
import test_admin as admin
import test_auth as support
from fastapi.testclient import TestClient
from PIL import Image
from receipts import new_receipt
from sqlalchemy import select
from sqlalchemy.orm import Session, sessionmaker

from app import media
from app.jobs import retention
from app.models import (
    AuditEvent,
    Destination,
    DestinationStatus,
    ModerationTask,
    Review,
    ReviewMedia,
    ReviewStatus,
)
from app.storage import MEDIA_BUCKET, get_storage

auth_env = support.auth_env
fake = support.fake
redis_fake = support.redis_fake
_reset_limiter = support._reset_limiter  # noqa: SLF001
BASE = "/api/v1/admin"


# ============================ files ============================


def jpeg_with_location(width: int = 640, height: int = 480) -> bytes:
    exif = Image.Exif()
    exif[0x010F] = "PhoneMaker"  # camera make
    exif[0x8825] = {1: "N", 2: (23.0, 48.0, 0.0), 3: "E", 4: (90.0, 24.0, 0.0)}  # GPS
    out = io.BytesIO()
    Image.new("RGB", (width, height), (40, 120, 60)).save(out, format="JPEG", exif=exif)
    return out.getvalue()


def _box(kind: bytes, payload: bytes) -> bytes:
    return struct.pack(">I", 8 + len(payload)) + kind + payload


def mp4(*, duration_ms: int = 30_000, video_codec: bytes = b"avc1", brand: bytes = b"isom", extra_track: bool = True) -> bytes:
    mvhd = _box(b"mvhd", b"\0\0\0\0" + struct.pack(">III", 0, 0, 1000) + struct.pack(">I", duration_ms) + b"\0" * 80)
    tkhd = _box(b"tkhd", b"\0\0\0\0" + b"\0" * 72 + struct.pack(">II", 640 << 16, 360 << 16))

    def track(handler: bytes, codec: bytes) -> bytes:
        hdlr = _box(b"hdlr", b"\0\0\0\0" + b"\0\0\0\0" + handler + b"\0" * 12 + b"\0")
        stsd = _box(b"stsd", b"\0\0\0\0" + struct.pack(">I", 1) + _box(codec, b"\0" * 16))
        minf = _box(b"minf", _box(b"stbl", stsd))
        return _box(b"trak", (tkhd if handler == b"vide" else b"") + _box(b"mdia", hdlr + minf))

    location = _box(b"udta", _box(b"\xa9xyz", b"+23.8000+090.4000/"))
    tracks = track(b"vide", video_codec) + track(b"soun", b"mp4a")
    if extra_track:
        tracks += track(b"meta", b"mebx")  # timed metadata, as phones write
    moov = _box(b"moov", mvhd + tracks + location)
    return _box(b"ftyp", brand + b"\0\0\0\0" + brand) + moov + _box(b"mdat", b"\x01" * 64)


def _check_video(data: bytes) -> tuple[tuple[int, int | None, int | None], bytes]:
    with tempfile.TemporaryFile() as f:
        f.write(data)
        result = media.check_and_strip_video(f, len(data))
        f.seek(0)
        return result, f.read()


# ============================ unit: images and videos ============================


def test_images_are_re_encoded_without_location_or_camera_data() -> None:
    processed, width, height = media.process_image(jpeg_with_location())
    with Image.open(io.BytesIO(processed)) as picture:
        assert picture.format == "WEBP" and (width, height) == (640, 480)
        assert not picture.getexif(), "no EXIF, so no GPS"
    assert b"PhoneMaker" not in processed


def test_large_images_are_scaled_down() -> None:
    out = io.BytesIO()
    Image.new("RGB", (4000, 1000)).save(out, format="PNG")
    _, width, height = media.process_image(out.getvalue())
    assert (width, height) == (2048, 512)


@pytest.mark.parametrize(
    ("data", "code"),
    [
        (b'<svg xmlns="http://www.w3.org/2000/svg"></svg>', "BROKEN"),
        (b"not an image at all", "BROKEN"),
        (jpeg_with_location()[:200], "BROKEN"),  # cut off
    ],
)
def test_bad_images_are_refused(data: bytes, code: str) -> None:
    with pytest.raises(media.MediaRejected) as caught:
        media.process_image(data)
    assert caught.value.code == code


def test_gif_and_oversized_images_are_refused() -> None:
    gif = io.BytesIO()
    Image.new("P", (10, 10)).save(gif, format="GIF")
    with pytest.raises(media.MediaRejected) as caught:
        media.process_image(gif.getvalue())
    assert caught.value.code == "TYPE"
    huge = io.BytesIO()
    Image.new("1", (5000, 4001)).save(huge, format="PNG")  # 20,005,000 pixels, tiny file
    with pytest.raises(media.MediaRejected) as caught:
        media.process_image(huge.getvalue())
    assert caught.value.code == "TOO_MANY_PIXELS"


def test_a_valid_mp4_is_accepted_and_its_metadata_blanked_in_place() -> None:
    original = mp4()
    (duration, width, height), cleaned = _check_video(original)
    assert (duration, width, height) == (30_000, 640, 360)
    assert len(cleaned) == len(original), "no byte offsets move"
    assert b"+23.8000" not in cleaned and b"mebx" not in cleaned, "location and the metadata track are gone"
    assert cleaned.endswith(_box(b"mdat", b"\x01" * 64)), "the media data is untouched"


@pytest.mark.parametrize(
    ("data", "code"),
    [
        (mp4(duration_ms=61_000), "TOO_LONG"),
        (mp4(video_codec=b"hvc1"), "VIDEO_CODEC"),
        (mp4(brand=b"qt  "), "TYPE"),
        (b"\0\0\0\x08free" + b"x" * 20, "TYPE"),
        (mp4()[:-30], "BROKEN"),
    ],
)
def test_bad_videos_are_refused(data: bytes, code: str) -> None:
    with pytest.raises(media.MediaRejected) as caught:
        _check_video(data)
    assert caught.value.code == code


# ============================ integration ============================


class MediaStorage:
    """In-memory Storage keyed by (bucket, key)."""

    def __init__(self) -> None:
        self.objects: dict[tuple[str, str], bytes] = {}
        self.deleted: list[str] = []

    def signed_upload_url(self, key: str, bucket: str = "verification-evidence") -> str:
        return f"http://storage.test/upload/{bucket}/{key}?token=t"

    def exists(self, key: str, bucket: str = "verification-evidence") -> bool:
        return (bucket, key) in self.objects

    def download(self, key: str, target: IO[bytes], bucket: str, max_bytes: int) -> int:
        data = self.objects[(bucket, key)]
        if len(data) > max_bytes:
            raise ValueError("too large")
        target.write(data)
        return len(data)

    def upload(self, key: str, data: Any, content_type: str, bucket: str) -> None:
        self.objects[(bucket, key)] = data if isinstance(data, bytes) else data.read()

    def delete(self, keys: list[str], bucket: str = "verification-evidence") -> None:
        self.deleted += keys
        for key in keys:
            self.objects.pop((bucket, key), None)

    def signed_download_url(self, key: str, bucket: str = "verification-evidence", seconds: int = 60) -> str:
        return f"http://storage.test/download/{bucket}/{key}?expires={seconds}"

    def signed_download_urls(self, keys: list[str], bucket: str, seconds: int) -> dict[str, str]:
        return {key: self.signed_download_url(key, bucket, seconds) for key in keys if (bucket, key) in self.objects}


@pytest.fixture()
def storage() -> MediaStorage:
    return MediaStorage()


@pytest.fixture()
def client(auth_env: None, postgres_session: Session, fake: support.FakeGoTrue, redis_fake: Any, storage: MediaStorage) -> TestClient:
    base = support.make_client(postgres_session, fake, redis_fake)
    base.app.dependency_overrides[get_storage] = lambda: storage  # type: ignore[attr-defined]
    return base


def _destination(session: Session) -> Destination:
    destination = Destination(status=DestinationStatus.PUBLISHED, name_bn="সাজেক", name_en="Sajek")
    session.add(destination)
    session.commit()
    return destination


def _review_body(destination: Destination, **overrides: Any) -> dict[str, Any]:
    body: dict[str, Any] = {
        "destination_id": str(destination.id),
        "client_draft_id": str(uuid.uuid4()),
        "receipt_secret": new_receipt(),
        "language": "EN",
        "traveller_type": "SOLO",
        "comfort_tier": "STANDARD",
        "visit_month": date.today().replace(day=1).isoformat(),
        "title": "Clouds over the hills",
        "body": "We watched the clouds roll over the hills at sunrise.",
        "overall_rating": 5,
        "consent_version": "v1",
    }
    body.update(overrides)
    return body


def _member_review(browser: TestClient, destination: Destination) -> str:
    response = browser.post("/api/v1/reviews/member", json=_review_body(destination))
    assert response.status_code == 201, response.text
    return str(response.json()["review_id"])


def _attach(browser: TestClient, storage: MediaStorage, review_id: str, data: bytes, content_type: str, **extra: Any) -> Any:
    intent = browser.post(
        f"/api/v1/reviews/{review_id}/media-intents",
        json={"content_type": content_type, "size_bytes": len(data), "alt_text": "The view", "ownership_declared": True, **extra},
    )
    assert intent.status_code == 201, intent.text
    key = intent.json()["upload_url"].split(f"/{MEDIA_BUCKET}/", 1)[1].split("?", 1)[0]
    storage.objects[(MEDIA_BUCKET, key)] = data  # what the browser's PUT to the signed URL does
    return browser.post(f"/api/v1/reviews/{review_id}/media/{intent.json()['media_id']}/complete")


@pytest.mark.integration
def test_a_signed_in_member_submits_a_review_in_their_own_name(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue) -> None:
    destination = _destination(postgres_session)
    nila = admin.staff_client(client, postgres_session, fake, "nila@example.com", None, "203.0.113.150", aal="aal1")
    body = _review_body(destination)
    first = nila.post("/api/v1/reviews/member", json=body)
    retry = nila.post("/api/v1/reviews/member", json=body)
    assert first.status_code == 201 and retry.status_code == 200 and retry.json()["duplicate_recovered"]
    review = postgres_session.get(Review, uuid.UUID(first.json()["review_id"]))
    assert review is not None and review.author_user_id == fake.users["nila@example.com"]["id"] and review.guest_display_name is None
    assert postgres_session.scalar(select(ModerationTask).where(ModerationTask.subject_id == review.id)), "queued for moderation"
    second = nila.post("/api/v1/reviews/member", json=_review_body(destination))
    assert second.status_code == 409 and second.json()["error"]["code"] == "MEMBER_REVIEW_EXISTS"
    anonymous = TestClient(client.app, base_url="https://localhost", headers={"Origin": support.ORIGIN})
    assert anonymous.post("/api/v1/reviews/member", json=_review_body(destination)).status_code == 401
    no_csrf = TestClient(client.app, base_url="https://localhost", headers={"Origin": support.ORIGIN, "X-Forwarded-For": "203.0.113.151"})
    no_csrf.cookies.set("__Host-abhijatri_session", fake.mint("nila@example.com").access_token)
    assert no_csrf.post("/api/v1/reviews/member", json=_review_body(destination)).status_code == 403


@pytest.mark.integration
def test_photos_and_a_video_are_checked_moderated_and_then_shown(
    client: TestClient, postgres_session: Session, fake: support.FakeGoTrue, storage: MediaStorage
) -> None:
    destination = _destination(postgres_session)
    nila = admin.staff_client(client, postgres_session, fake, "nila@example.com", None, "203.0.113.152", aal="aal1")
    review_id = _member_review(nila, destination)

    photo = _attach(nila, storage, review_id, jpeg_with_location(), "image/jpeg", caption="Sunrise")
    assert photo.status_code == 200 and photo.json()["state"] == "pending" and photo.json()["content_type"] == "image/webp"
    second_photo = _attach(nila, storage, review_id, jpeg_with_location(320, 240), "image/png")  # the browser's type is not trusted
    assert second_photo.status_code == 200
    video = _attach(nila, storage, review_id, mp4(), "video/mp4")
    assert video.status_code == 200 and video.json()["duration_ms"] == 30_000
    stored = [data for (bucket, key), data in storage.objects.items() if key.startswith("processed/")]
    assert len(stored) == 3 and all(b"+23.8000" not in d and b"PhoneMaker" not in d for d in stored)
    assert not any(key.startswith("quarantine/") for _, key in storage.objects), "quarantine copies are deleted"
    another_video = nila.post(f"/api/v1/reviews/{review_id}/media-intents", json={"content_type": "video/mp4", "size_bytes": 10, "alt_text": "x", "ownership_declared": True})
    assert another_video.status_code == 422 and another_video.json()["error"]["field_errors"][0]["code"] == "TOO_MANY"

    feed = client.get(f"/api/v1/destinations/{destination.id}/reviews").json()
    assert feed["items"] == [], "nothing public before moderation"

    mod = admin.staff_client(client, postgres_session, fake, "mod@example.com", "moderator", "203.0.113.153")
    queued = next(i for i in mod.get(f"{BASE}/queue").json()["items"] if i["subject"]["review_id"] == review_id)
    assert queued["subject"]["author_display_name"] and len(queued["subject"]["media"]) == 3
    preview = mod.post(f"{BASE}/submissions/{review_id}/media/{video.json()['id']}/url")
    assert preview.status_code == 200 and "expires=300" in preview.json()["url"]
    assert nila.post(f"{BASE}/submissions/{review_id}/media/{video.json()['id']}/url").status_code == 404, "members never see staff routes"

    task = postgres_session.scalar(select(ModerationTask).where(ModerationTask.subject_id == uuid.UUID(review_id)))
    review = postgres_session.get(Review, uuid.UUID(review_id))
    assert task is not None and review is not None
    lease = admin._claim(mod, task)["lease_token"]  # noqa: SLF001
    decided = mod.post(
        f"{BASE}/submissions/{review_id}/moderation-actions",
        json=admin._decision(task, lease, review, rejected_media_ids=[second_photo.json()["id"]]),  # noqa: SLF001
    )
    assert decided.status_code == 200, decided.text
    postgres_session.expire_all()
    states = {str(m.id): m.state for m in postgres_session.scalars(select(ReviewMedia))}
    assert states == {photo.json()["id"]: "approved", second_photo.json()["id"]: "rejected", video.json()["id"]: "approved"}
    audit = postgres_session.scalar(select(AuditEvent).where(AuditEvent.action == "review.publish"))
    assert audit is not None and audit.event_metadata["media"]["rejected"] == [second_photo.json()["id"]]

    item = client.get(f"/api/v1/destinations/{destination.id}/reviews").json()["items"][0]
    assert item["author_type"] == "MEMBER" and item["author_display_name"]
    assert [m["kind"] for m in item["media"]] == ["image", "video"]
    assert item["media"][0]["caption"] == "Sunrise" and item["media"][0]["url"].startswith("http://storage.test/download/")
    late = nila.post(f"/api/v1/reviews/{review_id}/media-intents", json={"content_type": "image/png", "size_bytes": 10, "alt_text": "x", "ownership_declared": True})
    assert late.status_code == 422 and late.json()["error"]["code"] == "TRANSITION_NOT_ALLOWED", "no new media after the decision"


@pytest.mark.integration
def test_upload_rules(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue, storage: MediaStorage) -> None:
    destination = _destination(postgres_session)
    nila = admin.staff_client(client, postgres_session, fake, "nila@example.com", None, "203.0.113.154", aal="aal1")
    review_id = _member_review(nila, destination)
    intents = f"/api/v1/reviews/{review_id}/media-intents"
    base = {"alt_text": "The view", "ownership_declared": True}

    assert nila.post(intents, json={**base, "content_type": "image/gif", "size_bytes": 10}).status_code == 422
    assert nila.post(intents, json={**base, "content_type": "image/svg+xml", "size_bytes": 10}).status_code == 422
    too_big = nila.post(intents, json={**base, "content_type": "image/jpeg", "size_bytes": media.IMAGE_MAX_BYTES + 1})
    assert too_big.status_code == 422 and too_big.json()["error"]["field_errors"][0]["code"] == "TOO_LARGE"
    assert nila.post(intents, json={**base, "content_type": "video/mp4", "size_bytes": media.VIDEO_MAX_BYTES + 1}).status_code == 422
    assert nila.post(intents, json={**base, "ownership_declared": False, "content_type": "image/jpeg", "size_bytes": 10}).status_code == 422
    assert nila.post(intents, json={"content_type": "image/jpeg", "size_bytes": 10, "ownership_declared": True}).status_code == 422, "alt text is required"

    broken = _attach(nila, storage, review_id, b"definitely not a jpeg", "image/jpeg")
    assert broken.status_code == 422 and broken.json()["error"]["field_errors"][0] == {"field": "file", "code": "BROKEN"}
    assert not storage.objects, "a refused upload is deleted at once"
    hevc = _attach(nila, storage, review_id, mp4(video_codec=b"hvc1"), "video/mp4")
    assert hevc.status_code == 422 and hevc.json()["error"]["field_errors"][0]["code"] == "VIDEO_CODEC"

    unsent = nila.post(intents, json={**base, "content_type": "image/jpeg", "size_bytes": 10})
    not_uploaded = nila.post(f"/api/v1/reviews/{review_id}/media/{unsent.json()['media_id']}/complete")
    assert not_uploaded.status_code == 422 and not_uploaded.json()["error"]["field_errors"][0]["code"] == "NOT_UPLOADED"

    for _ in range(4):
        assert _attach(nila, storage, review_id, jpeg_with_location(64, 64), "image/jpeg").status_code == 200
    sixth = nila.post(intents, json={**base, "content_type": "image/jpeg", "size_bytes": 10})
    assert sixth.status_code == 422 and sixth.json()["error"]["field_errors"][0]["code"] == "TOO_MANY", "five photos, the unsent one included"
    assert nila.post(f"/api/v1/reviews/{review_id}/media/{unsent.json()['media_id']}/remove").status_code == 204
    assert nila.post(intents, json={**base, "content_type": "image/jpeg", "size_bytes": 10}).status_code == 201, "removing frees a place"

    rafi = admin.staff_client(client, postgres_session, fake, "rafi@example.com", None, "203.0.113.155", aal="aal1")
    assert rafi.post(intents, json={**base, "content_type": "image/jpeg", "size_bytes": 10}).status_code == 404, "not your review"


@pytest.mark.integration
def test_a_rejected_review_rejects_its_media(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue, storage: MediaStorage) -> None:
    destination = _destination(postgres_session)
    nila = admin.staff_client(client, postgres_session, fake, "nila@example.com", None, "203.0.113.156", aal="aal1")
    review_id = _member_review(nila, destination)
    assert _attach(nila, storage, review_id, jpeg_with_location(), "image/jpeg").status_code == 200
    mod = admin.staff_client(client, postgres_session, fake, "mod@example.com", "moderator", "203.0.113.157")
    task = postgres_session.scalar(select(ModerationTask).where(ModerationTask.subject_id == uuid.UUID(review_id)))
    review = postgres_session.get(Review, uuid.UUID(review_id))
    assert task is not None and review is not None
    lease = admin._claim(mod, task)["lease_token"]  # noqa: SLF001
    wrong = mod.post(
        f"{BASE}/submissions/{review_id}/moderation-actions",
        json=admin._decision(task, lease, review, decision="REJECT", rejected_media_ids=[str(uuid.uuid4())]),  # noqa: SLF001
    )
    assert wrong.status_code == 422, "media ids only go with PUBLISH"
    rejected = mod.post(f"{BASE}/submissions/{review_id}/moderation-actions", json=admin._decision(task, lease, review, decision="REJECT"))  # noqa: SLF001
    assert rejected.status_code == 200
    postgres_session.expire_all()
    assert postgres_session.get(Review, uuid.UUID(review_id)).status == ReviewStatus.REJECTED  # type: ignore[union-attr]
    assert [m.state for m in postgres_session.scalars(select(ReviewMedia))] == ["rejected"]


@pytest.mark.integration
def test_abandoned_uploads_are_purged_after_a_day(client: TestClient, postgres_session: Session, fake: support.FakeGoTrue, storage: MediaStorage) -> None:
    destination = _destination(postgres_session)
    nila = admin.staff_client(client, postgres_session, fake, "nila@example.com", None, "203.0.113.158", aal="aal1")
    review_id = _member_review(nila, destination)
    unsent = nila.post(f"/api/v1/reviews/{review_id}/media-intents", json={"content_type": "image/jpeg", "size_bytes": 10, "alt_text": "x", "ownership_declared": True})
    assert unsent.status_code == 201
    sessions = sessionmaker(bind=postgres_session.get_bind(), expire_on_commit=False)
    assert retention.run(sessions, storage, datetime.now(UTC))["abandoned_media"] == 0  # type: ignore[arg-type]
    assert retention.run(sessions, storage, datetime.now(UTC) + timedelta(hours=25))["abandoned_media"] == 1  # type: ignore[arg-type]
    postgres_session.expire_all()
    assert postgres_session.scalar(select(ReviewMedia)) is None and storage.deleted
