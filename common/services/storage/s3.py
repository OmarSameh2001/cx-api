"""Any S3-compatible store: Supabase Storage, Cloudflare R2, AWS S3."""

from datetime import datetime, timedelta, timezone
from typing import Optional
from urllib.parse import quote

import boto3
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from config import FilesEnv

from .base import ObjectInfo, StorageError, StorageProvider, UploadTarget


def _disposition(name: str, inline: bool) -> str:
    kind = "inline" if inline else "attachment"
    ascii_name = name.encode("ascii", "ignore").decode().replace('"', "") or "file"
    return f"{kind}; filename=\"{ascii_name}\"; filename*=UTF-8''{quote(name)}"


class S3Storage(StorageProvider):
    name = "s3"

    def __init__(self) -> None:
        if not (FilesEnv.S3_ACCESS_KEY_ID and FilesEnv.S3_SECRET_ACCESS_KEY):
            raise StorageError("S3_ACCESS_KEY_ID and S3_SECRET_ACCESS_KEY must be set")
        self.bucket = FilesEnv.S3_BUCKET
        self.client = boto3.client(
            "s3",
            endpoint_url=FilesEnv.S3_ENDPOINT_URL,
            region_name=FilesEnv.S3_REGION,
            aws_access_key_id=FilesEnv.S3_ACCESS_KEY_ID,
            aws_secret_access_key=FilesEnv.S3_SECRET_ACCESS_KEY,
            config=Config(
                signature_version="s3v4",
                s3={"addressing_style": "path"},
                retries={"max_attempts": 3, "mode": "standard"},
                connect_timeout=5,
                read_timeout=30,
                # newer botocore adds checksum headers a browser PUT can't send
                request_checksum_calculation="when_required",
                response_checksum_validation="when_required",
            ),
        )

    def signed_upload(self, key, *, content_type, size, expires_in) -> UploadTarget:
        try:
            url = self.client.generate_presigned_url(
                "put_object",
                Params={"Bucket": self.bucket, "Key": key, "ContentType": content_type},
                ExpiresIn=expires_in,
            )
        except (BotoCoreError, ClientError) as exc:
            raise StorageError(str(exc)) from exc
        return UploadTarget(
            method="PUT",
            url=url,
            headers={"Content-Type": content_type},
            expires_at=datetime.now(timezone.utc) + timedelta(seconds=expires_in),
        )

    def signed_link(self, key, *, download_name, content_type, expires_in, inline=False) -> str:
        try:
            return self.client.generate_presigned_url(
                "get_object",
                Params={
                    "Bucket": self.bucket,
                    "Key": key,
                    "ResponseContentDisposition": _disposition(download_name, inline),
                    "ResponseContentType": content_type,
                },
                ExpiresIn=expires_in,
            )
        except (BotoCoreError, ClientError) as exc:
            raise StorageError(str(exc)) from exc

    def head(self, key, *, content_type="") -> Optional[ObjectInfo]:
        try:
            res = self.client.head_object(Bucket=self.bucket, Key=key)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") in ("404", "NoSuchKey", "NotFound"):
                return None
            raise StorageError(str(exc)) from exc
        except BotoCoreError as exc:
            raise StorageError(str(exc)) from exc
        return ObjectInfo(
            size=int(res["ContentLength"]),
            content_type=res.get("ContentType"),
            etag=(res.get("ETag") or "").strip('"') or None,
        )

    def delete(self, key, *, content_type="") -> None:
        try:
            self.client.delete_object(Bucket=self.bucket, Key=key)
        except ClientError as exc:
            if exc.response.get("Error", {}).get("Code") not in ("404", "NoSuchKey", "NotFound"):
                raise StorageError(str(exc)) from exc
        except BotoCoreError as exc:
            raise StorageError(str(exc)) from exc

    def put_bytes(self, key, data, *, content_type) -> ObjectInfo:
        try:
            res = self.client.put_object(Bucket=self.bucket, Key=key, Body=data, ContentType=content_type)
        except (BotoCoreError, ClientError) as exc:
            raise StorageError(str(exc)) from exc
        return ObjectInfo(size=len(data), content_type=content_type, etag=(res.get("ETag") or "").strip('"') or None)

    def get_bytes(self, key, *, max_bytes, content_type="") -> bytes:
        try:
            res = self.client.get_object(Bucket=self.bucket, Key=key)
            if int(res["ContentLength"]) > max_bytes:
                raise StorageError(f"object is larger than {max_bytes} bytes")
            return res["Body"].read(max_bytes + 1)[:max_bytes]
        except (BotoCoreError, ClientError) as exc:
            raise StorageError(str(exc)) from exc
