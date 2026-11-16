"""Pick a storage provider by name. To add a provider, write a class that
implements StorageProvider and add one line to _FACTORIES."""

import threading
from typing import Callable

from config import FilesEnv

from .base import ObjectInfo, StorageError, StorageProvider, UploadTarget

__all__ = ["ObjectInfo", "StorageError", "StorageProvider", "UploadTarget", "default_provider_name", "get_storage"]


def _s3() -> StorageProvider:
    from .s3 import S3Storage

    return S3Storage()


def _cloudinary() -> StorageProvider:
    from .cloudinary import CloudinaryStorage

    return CloudinaryStorage()


_FACTORIES: dict[str, Callable[[], StorageProvider]] = {"s3": _s3, "cloudinary": _cloudinary}
_instances: dict[str, StorageProvider] = {}
_lock = threading.Lock()


def default_provider_name() -> str:
    return FilesEnv.STORAGE_PROVIDER


def get_storage(name: str | None = None) -> StorageProvider:
    """The provider a file lives in (pass its stored name), or the default."""
    name = name or default_provider_name()
    if name not in _FACTORIES and name not in _instances:
        raise StorageError(f"unknown storage provider {name!r}")
    with _lock:
        if name not in _instances:
            _instances[name] = _FACTORIES[name]()
        return _instances[name]


def set_storage_for_tests(name: str, provider: StorageProvider) -> None:
    _instances[name] = provider


def reset_storage_for_tests() -> None:
    _instances.clear()
