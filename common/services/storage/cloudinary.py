"""Cloudinary, through its REST API (no SDK). Files are stored with
type=authenticated, so they can only be fetched through signed links.

On Cloudinary's free plan signed links do not expire (expiring links need
its token-based auth), so prefer the S3 provider for private files.
"""

import base64
import hashlib
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

import requests

from config import FilesEnv

from .base import ObjectInfo, StorageError, StorageProvider, UploadTarget

_API = "https://api.cloudinary.com/v1_1"
_CDN = "https://res.cloudinary.com"
_TIMEOUT = 30


def _resource_type(content_type: str) -> str:
    if content_type.startswith("image/"):
        return "image"
    if content_type.startswith(("video/", "audio/")):
        return "video"
    return "raw"


class CloudinaryStorage(StorageProvider):
    name = "cloudinary"

    def __init__(self) -> None:
        if not (FilesEnv.CLOUDINARY_CLOUD_NAME and FilesEnv.CLOUDINARY_API_KEY and FilesEnv.CLOUDINARY_API_SECRET):
            raise StorageError("CLOUDINARY_CLOUD_NAME, CLOUDINARY_API_KEY and CLOUDINARY_API_SECRET must be set")
        self.cloud = FilesEnv.CLOUDINARY_CLOUD_NAME
        self.key = FilesEnv.CLOUDINARY_API_KEY
        self.secret = FilesEnv.CLOUDINARY_API_SECRET

    def _signed_params(self, **params) -> dict:
        params["timestamp"] = int(time.time())
        to_sign = "&".join(f"{k}={params[k]}" for k in sorted(params) if params[k] not in (None, ""))
        params["signature"] = hashlib.sha1((to_sign + self.secret).encode()).hexdigest()
        params["api_key"] = self.key
        return params

    def signed_upload(self, key, *, content_type, size, expires_in) -> UploadTarget:
        fields = self._signed_params(public_id=key, type="authenticated", overwrite="true")
        return UploadTarget(
            method="POST",
            url=f"{_API}/{self.cloud}/{_resource_type(content_type)}/upload",
            fields={k: str(v) for k, v in fields.items()},
            # Cloudinary accepts a signed upload for one hour
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=min(expires_in, 3600)),
        )

    def signed_link(self, key, *, download_name, content_type, expires_in, inline=False) -> str:
        digest = hashlib.sha1((key + self.secret).encode()).digest()
        sig = base64.urlsafe_b64encode(digest).decode()[:8]
        return f"{_CDN}/{self.cloud}/{_resource_type(content_type)}/authenticated/s--{sig}--/{key}"

    def head(self, key, *, content_type="") -> Optional[ObjectInfo]:
        try:
            res = requests.get(
                f"{_API}/{self.cloud}/resources/{_resource_type(content_type)}/authenticated/{key}",
                auth=(self.key, self.secret),
                timeout=_TIMEOUT,
            )
        except requests.RequestException as exc:
            raise StorageError(str(exc)) from exc
        if res.status_code == 404:
            return None
        if not res.ok:
            raise StorageError(f"cloudinary head failed: {res.status_code} {res.text[:200]}")
        body = res.json()
        return ObjectInfo(size=int(body.get("bytes", 0)), content_type=None, etag=body.get("etag"))

    def delete(self, key, *, content_type="") -> None:
        params = self._signed_params(public_id=key, type="authenticated", invalidate="true")
        try:
            res = requests.post(
                f"{_API}/{self.cloud}/{_resource_type(content_type)}/destroy", data=params, timeout=_TIMEOUT
            )
        except requests.RequestException as exc:
            raise StorageError(str(exc)) from exc
        if not res.ok:
            raise StorageError(f"cloudinary delete failed: {res.status_code} {res.text[:200]}")

    def put_bytes(self, key, data, *, content_type) -> ObjectInfo:
        params = self._signed_params(public_id=key, type="authenticated", overwrite="true")
        try:
            res = requests.post(
                f"{_API}/{self.cloud}/{_resource_type(content_type)}/upload",
                data=params,
                files={"file": ("file", data, content_type)},
                timeout=_TIMEOUT,
            )
        except requests.RequestException as exc:
            raise StorageError(str(exc)) from exc
        if not res.ok:
            raise StorageError(f"cloudinary upload failed: {res.status_code} {res.text[:200]}")
        return ObjectInfo(size=len(data), content_type=content_type, etag=res.json().get("etag"))

    def get_bytes(self, key, *, max_bytes, content_type="") -> bytes:
        url = self.signed_link(key, download_name="file", content_type=content_type, expires_in=60)
        try:
            with requests.get(url, stream=True, timeout=_TIMEOUT) as res:
                if not res.ok:
                    raise StorageError(f"cloudinary download failed: {res.status_code}")
                data = bytearray()
                for chunk in res.iter_content(64 * 1024):
                    data.extend(chunk)
                    if len(data) > max_bytes:
                        raise StorageError(f"object is larger than {max_bytes} bytes")
                return bytes(data)
        except requests.RequestException as exc:
            raise StorageError(str(exc)) from exc
