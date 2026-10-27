"""Private storage on Supabase Storage: verification evidence (Moderation spec 3.3) and review media.

Both buckets are private. The browser never holds a Supabase key: it receives a one-time signed
upload URL for one object, and staff receive a signed download URL that lives 60 seconds, issued
only after the API has checked their right to that case. The service-role key stays on the server.
"""

import logging
from typing import IO, Any

import httpx

from app.config import get_settings

logger = logging.getLogger(__name__)

BUCKET = "verification-evidence"
MAX_BYTES = 5 * 1024 * 1024
ALLOWED_TYPES = ("image/jpeg", "image/png", "application/pdf")
DOWNLOAD_SECONDS = 60

# Review photos and videos (Review.md 8, amendment A4). Uploads land under `quarantine/`; only the
# server-checked copy under `processed/` is ever shown, through signed links.
MEDIA_BUCKET = "review-media"
MEDIA_MAX_BYTES = 50 * 1024 * 1024
MEDIA_TYPES = ("image/jpeg", "image/png", "image/webp", "video/mp4")

_BUCKETS: dict[str, tuple[int, tuple[str, ...]]] = {
    BUCKET: (MAX_BYTES, ALLOWED_TYPES),
    MEDIA_BUCKET: (MEDIA_MAX_BYTES, MEDIA_TYPES),
}


class StorageUnavailable(Exception):
    pass


class StorageClient:
    def __init__(self, *, transport: httpx.BaseTransport | None = None) -> None:
        self._transport = transport
        self._ready: set[str] = set()

    def _auth(self) -> tuple[str, dict[str, str]]:
        settings = get_settings()
        if not (settings.supabase_url and settings.supabase_service_role_key):
            raise StorageUnavailable("not configured")
        key = settings.supabase_service_role_key
        return f"{settings.supabase_url}/storage/v1", {"apikey": key, "Authorization": f"Bearer {key}"}

    def _call(
        self,
        method: str,
        path: str,
        *,
        json: Any = None,
        content: Any = None,
        headers: dict[str, str] | None = None,
        timeout: float = 10,
    ) -> httpx.Response:
        base, auth = self._auth()
        try:
            with httpx.Client(base_url=base, timeout=timeout, transport=self._transport) as client:
                return client.request(method, path, json=json, content=content, headers={**auth, **(headers or {})})
        except httpx.HTTPError as error:
            logger.warning("storage unreachable: %s", type(error).__name__)
            raise StorageUnavailable(type(error).__name__) from error

    def public_url(self, relative: str) -> str:
        """Storage answers with paths relative to `/storage/v1`; the browser needs the full address."""
        return f"{get_settings().supabase_url}/storage/v1{relative}"

    def ensure_bucket(self, bucket: str = BUCKET) -> None:
        if bucket in self._ready:
            return
        max_bytes, types = _BUCKETS[bucket]
        response = self._call(
            "POST",
            "/bucket",
            json={"id": bucket, "name": bucket, "public": False, "file_size_limit": max_bytes, "allowed_mime_types": list(types)},
        )
        if response.status_code not in (200, 201, 400, 409):  # 400/409: it already exists
            raise StorageUnavailable(f"bucket {response.status_code}")
        self._ready.add(bucket)

    def signed_upload_url(self, object_key: str, bucket: str = BUCKET) -> str:
        self.ensure_bucket(bucket)
        response = self._call("POST", f"/object/upload/sign/{bucket}/{object_key}")
        if response.status_code != 200:
            raise StorageUnavailable(f"upload sign {response.status_code}")
        return self.public_url(str(response.json()["url"]))

    def exists(self, object_key: str, bucket: str = BUCKET) -> bool:
        response = self._call("GET", f"/object/info/authenticated/{bucket}/{object_key}")
        if response.status_code == 200:
            return True
        if response.status_code in (400, 404):
            return False
        raise StorageUnavailable(f"info {response.status_code}")

    def signed_download_url(self, object_key: str, bucket: str = BUCKET, seconds: int = DOWNLOAD_SECONDS) -> str:
        response = self._call("POST", f"/object/sign/{bucket}/{object_key}", json={"expiresIn": seconds})
        if response.status_code != 200:
            raise StorageUnavailable(f"download sign {response.status_code}")
        body = response.json()
        return self.public_url(str(body.get("signedURL") or body.get("signedUrl")))

    def signed_download_urls(self, object_keys: list[str], bucket: str, seconds: int) -> dict[str, str]:
        """Sign many objects in one call; a key Storage cannot sign is left out."""
        if not object_keys:
            return {}
        response = self._call("POST", f"/object/sign/{bucket}", json={"expiresIn": seconds, "paths": object_keys})
        if response.status_code != 200:
            raise StorageUnavailable(f"download sign {response.status_code}")
        urls: dict[str, str] = {}
        for entry in response.json():
            signed = entry.get("signedURL") or entry.get("signedUrl")
            if signed and not entry.get("error"):
                urls[str(entry["path"])] = self.public_url(str(signed))
        return urls

    def download(self, object_key: str, target: IO[bytes], bucket: str, max_bytes: int) -> int:
        """Copy an object into ``target``. Raises ``ValueError`` (and stops reading) past ``max_bytes``."""
        base, auth = self._auth()
        total = 0
        try:
            with httpx.Client(timeout=60, transport=self._transport) as client, client.stream(
                "GET", f"{base}/object/authenticated/{bucket}/{object_key}", headers=auth
            ) as response:
                if response.status_code != 200:
                    raise StorageUnavailable(f"download {response.status_code}")
                for chunk in response.iter_bytes():
                    total += len(chunk)
                    if total > max_bytes:
                        raise ValueError("object larger than allowed")
                    target.write(chunk)
        except httpx.HTTPError as error:
            logger.warning("storage unreachable: %s", type(error).__name__)
            raise StorageUnavailable(type(error).__name__) from error
        return total

    def upload(self, object_key: str, data: bytes | IO[bytes], content_type: str, bucket: str) -> None:
        self.ensure_bucket(bucket)
        response = self._call(
            "POST",
            f"/object/{bucket}/{object_key}",
            content=data,
            headers={"Content-Type": content_type, "x-upsert": "true"},
            timeout=120,
        )
        if response.status_code not in (200, 201):
            raise StorageUnavailable(f"upload {response.status_code}")

    def delete(self, object_keys: list[str], bucket: str = BUCKET) -> None:
        if not object_keys:
            return
        response = self._call("DELETE", f"/object/{bucket}", json={"prefixes": object_keys})
        if response.status_code not in (200, 204, 404):
            raise StorageUnavailable(f"delete {response.status_code}")


_client = StorageClient()


def get_storage() -> StorageClient:
    """Dependency so tests substitute a fake."""
    return _client
