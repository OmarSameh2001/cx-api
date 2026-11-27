"""What files are for, with the code defaults for each purpose.

Defaults are the bottom layer of the limits. The platform admin can change
them per purpose (file_limits rows with no organisation), an organisation
admin can tighten them for their organisation, and a form question can
tighten them for that question. FILES_HARD_MAX_MB caps everything.

Adding a purpose: one entry in PURPOSES, plus who may attach it (service).
"""

from dataclasses import dataclass, field

from common.services.images import ImagePolicy

MB = 1024 * 1024

IMAGE_TYPES = ("image/jpeg", "image/png", "image/webp", "image/gif", "image/heic", "image/heif")
DOCUMENT_TYPES = (
    "application/pdf",
    "application/msword",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-powerpoint",
    "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    "text/plain",
    "text/csv",
)

# Never accepted, whatever a limit says: these can run as a page or script
# when opened from a link.
BLOCKED_TYPES = (
    "text/html",
    "application/xhtml+xml",
    "image/svg+xml",
    "application/javascript",
    "text/javascript",
    "application/x-msdownload",
    "application/x-sh",
)


@dataclass(frozen=True)
class Purpose:
    name: str
    max_mb: float
    allowed_types: tuple[str, ...]
    image: ImagePolicy = field(default_factory=ImagePolicy)
    # what a file of this purpose can be attached to
    attach_types: tuple[str, ...] = ()
    # can anonymous respondents of a public form upload it
    public: bool = False
    link_ttl_seconds: int | None = None


PURPOSES: dict[str, Purpose] = {
    p.name: p
    for p in (
        Purpose(
            "form_answer",
            max_mb=10,
            allowed_types=IMAGE_TYPES + DOCUMENT_TYPES,
            image=ImagePolicy(max_side=1600, quality=80, format="webp", thumb_side=320),
            attach_types=("submission",),
            public=True,
        ),
        # pictures in a form: on questions, options, blocks, the cover and
        # background (E2.1). Uploaded by the form's editors, attached to the
        # form when it is saved, and shown to everyone who opens the form.
        Purpose(
            "form_media",
            max_mb=5,
            allowed_types=("image/png", "image/jpeg", "image/webp"),
            image=ImagePolicy(max_side=1600, quality=85, format="webp", thumb_side=320),
            attach_types=("form",),
            # a respondent may take a while over a form
            link_ttl_seconds=3600,
        ),
        Purpose(
            "org_logo",
            max_mb=2,
            allowed_types=("image/png", "image/jpeg", "image/webp"),
            # webp keeps transparency
            image=ImagePolicy(max_side=512, quality=90, format="webp", thumb_side=128),
            attach_types=("organisation",),
            # logos are shown on every page; a longer link saves refetching
            link_ttl_seconds=3600,
        ),
    )
}


def type_matches(content_type: str, pattern: str) -> bool:
    if pattern in ("*/*", content_type):
        return True
    return pattern.endswith("/*") and content_type.startswith(pattern[:-1])


def type_allowed(content_type: str, patterns: tuple[str, ...] | list[str]) -> bool:
    if content_type in BLOCKED_TYPES:
        return False
    return any(type_matches(content_type, p) for p in patterns)


def intersect_types(a: tuple[str, ...] | list[str], b: tuple[str, ...] | list[str]) -> tuple[str, ...]:
    """Types allowed by both lists, wildcard aware: image/* with image/png
    gives image/png."""
    out = [x for x in a if any(type_matches(x, p) for p in b)]
    out += [y for y in b if y not in out and any(type_matches(y, p) for p in a)]
    return tuple(dict.fromkeys(out))
