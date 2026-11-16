"""The storage provider interface. Files never pass through the API: the
browser uploads straight to the provider with a short-lived signed target,
and downloads through a short-lived signed link."""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Literal, Optional


@dataclass(frozen=True)
class UploadTarget:
    """How the browser sends the bytes. PUT: the raw file as the body, with
    `headers`. POST: multipart form with `fields`, then the file as `file`."""

    method: Literal["PUT", "POST"]
    url: str
    expires_at: datetime
    headers: dict[str, str] = field(default_factory=dict)
    fields: dict[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ObjectInfo:
    size: int
    content_type: Optional[str]
    etag: Optional[str]


class StorageError(Exception):
    pass


class StorageProvider(ABC):
    """`content_type` on head/delete/get_bytes is the file's stored type:
    providers that keep kinds of files apart (Cloudinary) need it."""

    name: str

    @abstractmethod
    def signed_upload(self, key: str, *, content_type: str, size: int, expires_in: int) -> UploadTarget: ...

    @abstractmethod
    def signed_link(
        self, key: str, *, download_name: str, content_type: str, expires_in: int, inline: bool = False
    ) -> str: ...

    @abstractmethod
    def head(self, key: str, *, content_type: str = "") -> Optional[ObjectInfo]:
        """The stored object's real size and type, or None if it's missing."""

    @abstractmethod
    def delete(self, key: str, *, content_type: str = "") -> None:
        """Removes the object; a missing object is not an error."""

    @abstractmethod
    def put_bytes(self, key: str, data: bytes, *, content_type: str) -> ObjectInfo: ...

    @abstractmethod
    def get_bytes(self, key: str, *, max_bytes: int, content_type: str = "") -> bytes: ...
