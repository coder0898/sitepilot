"""Evidence bytes live in the private `evidence` bucket in Supabase Storage
(see supabase/migrations/202608240001_v2_evidence_storage_bucket.sql), not
on local disk. The backend's container filesystem is wiped on every
restart/redeploy/sleep-wake cycle on its hosting platform, which would
silently destroy evidence photos before an approver ever reviews them.

Every read/write/delete of evidence bytes goes through this module, mirroring
`supabase_auth.py`'s plain-urllib call style for Supabase's own HTTP APIs
rather than pulling in a storage SDK for three calls.
"""

from __future__ import annotations

from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from app.config import settings

_BUCKET = "evidence"


class EvidenceStorageError(Exception):
    def __init__(self, message: str, status_code: int = 502):
        self.status_code = status_code
        super().__init__(message)


def _configuration() -> tuple[str, str]:
    url = settings.supabase_url.rstrip("/")
    if not url or not settings.supabase_secret_key:
        raise EvidenceStorageError("Evidence storage is not configured on the server.", 503)
    return url, settings.supabase_secret_key


def write(storage_key: str, data: bytes, content_type: str) -> None:
    url, secret_key = _configuration()
    headers = {
        "apikey": secret_key,
        "Authorization": f"Bearer {secret_key}",
        "Content-Type": content_type,
    }
    try:
        with urlopen(
            Request(f"{url}/storage/v1/object/{_BUCKET}/{storage_key}", data=data, headers=headers, method="POST"),
            timeout=30,
        ):
            pass
    except HTTPError as exc:
        raise EvidenceStorageError("Evidence storage rejected the upload.", exc.code) from exc
    except (URLError, TimeoutError) as exc:
        raise EvidenceStorageError("Evidence storage is temporarily unavailable.", 503) from exc


def read(storage_key: str) -> bytes | None:
    url, secret_key = _configuration()
    headers = {"apikey": secret_key, "Authorization": f"Bearer {secret_key}"}
    try:
        with urlopen(
            Request(f"{url}/storage/v1/object/{_BUCKET}/{storage_key}", headers=headers, method="GET"),
            timeout=30,
        ) as response:
            return response.read()
    except HTTPError as exc:
        if exc.code == 404:
            return None
        raise EvidenceStorageError("Evidence storage is temporarily unavailable.", 503) from exc
    except (URLError, TimeoutError) as exc:
        raise EvidenceStorageError("Evidence storage is temporarily unavailable.", 503) from exc


def delete(storage_key: str) -> None:
    url, secret_key = _configuration()
    headers = {"apikey": secret_key, "Authorization": f"Bearer {secret_key}"}
    try:
        with urlopen(
            Request(f"{url}/storage/v1/object/{_BUCKET}/{storage_key}", headers=headers, method="DELETE"),
            timeout=30,
        ):
            pass
    except HTTPError as exc:
        if exc.code != 404:
            raise EvidenceStorageError("Evidence storage rejected the delete.", exc.code) from exc
    except (URLError, TimeoutError) as exc:
        raise EvidenceStorageError("Evidence storage is temporarily unavailable.", 503) from exc
