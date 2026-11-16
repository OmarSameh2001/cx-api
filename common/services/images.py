"""Image compression, WhatsApp style: shrink to a maximum side, re-encode at
a quality where the loss isn't visible, fix rotation from EXIF, and strip
all metadata (camera, GPS). The browser does the same before upload; this is
the server-side safety net and the thumbnail maker.
"""

from dataclasses import dataclass
from io import BytesIO
from typing import Literal, Optional

from PIL import Image, ImageOps, UnidentifiedImageError

from config import FilesEnv

try:  # iPhone photos
    from pillow_heif import register_heif_opener

    register_heif_opener()
    HEIF_SUPPORTED = True
except ImportError:  # pragma: no cover
    HEIF_SUPPORTED = False

Image.MAX_IMAGE_PIXELS = FilesEnv.IMAGE_MAX_PIXELS

OutputFormat = Literal["webp", "jpeg", "png", "keep"]

# types the image service can read
PROCESSABLE = {
    "image/jpeg", "image/png", "image/webp", "image/gif", "image/bmp", "image/tiff",
    "image/heic", "image/heif",
}

_PIL_FORMAT = {"webp": "WEBP", "jpeg": "JPEG", "png": "PNG"}
_MIME = {"webp": "image/webp", "jpeg": "image/jpeg", "png": "image/png"}
_FROM_PIL = {"JPEG": "jpeg", "PNG": "png", "WEBP": "webp"}


class ImageError(Exception):
    pass


@dataclass(frozen=True)
class ImagePolicy:
    compress: bool = True
    max_side: int = 1600
    quality: int = 80
    format: OutputFormat = "webp"
    # skip compression entirely (document scans where every pixel matters)
    keep_original: bool = False
    # 0 means no thumbnail
    thumb_side: int = 320


@dataclass(frozen=True)
class ProcessedImage:
    data: bytes
    content_type: str
    extension: str
    width: int
    height: int


def _open(data: bytes) -> Image.Image:
    try:
        img = Image.open(BytesIO(data))
        img.load()
    except Image.DecompressionBombError as exc:
        raise ImageError("image has too many pixels") from exc
    except (UnidentifiedImageError, OSError, ValueError) as exc:
        raise ImageError("not a readable image") from exc
    return img


def _encode(img: Image.Image, fmt: str, quality: int) -> bytes:
    out = BytesIO()
    if fmt == "jpeg":
        if img.mode in ("RGBA", "LA", "P"):
            img = img.convert("RGBA")
            flat = Image.new("RGB", img.size, (255, 255, 255))
            flat.paste(img, mask=img.getchannel("A"))
            img = flat
        elif img.mode != "RGB":
            img = img.convert("RGB")
        img.save(out, "JPEG", quality=quality, optimize=True, progressive=True)
    elif fmt == "webp":
        if img.mode not in ("RGB", "RGBA"):
            img = img.convert("RGBA" if "A" in img.getbands() or img.mode == "P" else "RGB")
        img.save(out, "WEBP", quality=quality, method=4)
    else:
        img.save(out, "PNG", optimize=True)
    return out.getvalue()


def compress(data: bytes, policy: ImagePolicy) -> Optional[ProcessedImage]:
    """The compressed image, or None when the original should be kept
    (policy says so, it's animated, or it's already small and clean)."""
    if policy.keep_original or not policy.compress:
        return None
    img = _open(data)
    if getattr(img, "is_animated", False):
        return None

    source_fmt = _FROM_PIL.get(img.format or "")
    had_metadata = bool(img.info.get("exif") or img.getexif())
    rotated = ImageOps.exif_transpose(img)
    resized = max(rotated.size) > policy.max_side
    if resized:
        rotated.thumbnail((policy.max_side, policy.max_side), Image.Resampling.LANCZOS)

    fmt = source_fmt if policy.format == "keep" else policy.format
    if fmt not in _PIL_FORMAT:  # HEIC, BMP, TIFF... always become a web format
        fmt = "webp"
    encoded = _encode(rotated, fmt, policy.quality)

    # already small, same format, nothing to strip: keep the original bytes
    if not resized and not had_metadata and fmt == source_fmt and len(encoded) >= len(data):
        return None
    # never make a file bigger unless it removes metadata (GPS) or a format
    # browsers can't show
    if not resized and len(encoded) > len(data) and fmt == source_fmt and not had_metadata:
        return None
    return ProcessedImage(encoded, _MIME[fmt], fmt if fmt != "jpeg" else "jpg", *rotated.size)


def dimensions(data: bytes) -> tuple[int, int]:
    """Width and height as displayed (after EXIF rotation)."""
    img = _open(data)
    w, h = img.size
    orientation = img.getexif().get(0x0112, 1)
    return (h, w) if orientation in (5, 6, 7, 8) else (w, h)


def thumbnail(data: bytes, side: int) -> ProcessedImage:
    img = ImageOps.exif_transpose(_open(data))
    img.thumbnail((side, side), Image.Resampling.LANCZOS)
    return ProcessedImage(_encode(img, "webp", 75), "image/webp", "webp", *img.size)
