"""The file service: the only way any module stores, reads or removes files.

    from modules.files import service as files

    files.add(...)        start an upload: checks limits, returns a signed upload target
    files.complete(...)   confirm it: checks the stored size and type, marks it ready
    files.update(...)     replace the content (same id; the old bytes go once the new are confirmed)
    files.rename(...)     change the display name
    files.delete(...)     remove it (row and stored bytes)
    files.get(...) / files.list_files(...) / files.link(...)
    files.attach(...) / files.detach(...)   tie it to a record (no commit: caller's transaction)
    files.put_bytes(...)  store bytes the server made (exports...)
    files.effective_limits(...) / set_limit(...) / delete_limit(...)

Every call checks organisation and permissions itself, so callers can't skip
them. Stored objects are only ever deleted by the cleanup job (or right after
a commit), never mid-transaction: a rolled-back transaction can't leave a row
pointing at deleted bytes.
"""

import hashlib
import hmac
import re
import secrets
import uuid
from dataclasses import asdict, dataclass, field as dc_field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional, Union

from fastapi import HTTPException, status
from loguru import logger
from sqlalchemy.orm import Session

from common.errors import AppError, CodedHTTPException
from common.services import images
from common.services.images import ImagePolicy
from common.services.storage import StorageError, UploadTarget, default_provider_name, get_storage
from config import FilesEnv
from modules.auth.dto import EmployeePrincipal

from . import repository
from .model import FileLimit, StoredFile
from .purposes import MB, PURPOSES, Purpose, intersect_types, type_allowed

# --- actors ------------------------------------------------------------------


@dataclass(frozen=True)
class PublicActor:
    """An anonymous respondent of a public form. `token` is the file secret
    handed out with the upload; only its hash is stored."""

    form_id: int
    token: Optional[str] = None


Actor = Union[EmployeePrincipal, PublicActor]


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _not_found() -> HTTPException:
    return AppError(404, "files.not_found")


def _can_manage_org(actor: Actor, organisation_id: int) -> bool:
    return isinstance(actor, EmployeePrincipal) and (
        actor.is_platform_admin or (actor.is_admin and actor.organisation_id == organisation_id)
    )


def _is_owner(file: StoredFile, actor: Actor) -> bool:
    if isinstance(actor, PublicActor):
        return bool(
            actor.token
            and file.owner_token_hash
            and file.form_id == actor.form_id
            and hmac.compare_digest(file.owner_token_hash, _hash_token(actor.token))
        )
    return file.owner_employee_id is not None and file.owner_employee_id == actor.id


def _ensure_same_org(file: StoredFile, actor: Actor) -> None:
    if isinstance(actor, EmployeePrincipal) and not actor.is_platform_admin:
        if file.organisation_id != actor.organisation_id:
            raise _not_found()


def _ensure_can_view(db: Session, file: StoredFile, actor: Actor) -> None:
    _ensure_same_org(file, actor)
    if file.status != "ready":
        raise _not_found()
    if _is_owner(file, actor):
        return
    if isinstance(actor, EmployeePrincipal):
        if file.purpose == "org_logo" or actor.is_platform_admin:
            return
        if file.attached_type == "submission" and file.attached_id is not None:
            from modules.forms import access as form_access
            from modules.submissions import repository as submissions_repository

            submission = submissions_repository.get_submission(db, file.attached_id)
            if submission is not None and (
                submission.user_id == actor.id
                or (submission.form is not None and form_access.can_review(actor, submission.form))
            ):
                return
    raise _not_found()


def _ensure_can_modify(db: Session, file: StoredFile, actor: Actor) -> None:
    _ensure_same_org(file, actor)
    if file.status == "deleted":
        raise _not_found()
    if file.purpose == "org_logo":
        if _can_manage_org(actor, file.organisation_id):
            return
        raise AppError(403, "files.logo_admin_only")
    if not _is_owner(file, actor):
        raise _not_found()
    if file.attached_type == "submission" and file.attached_id is not None:
        from modules.submissions import repository as submissions_repository

        submission = submissions_repository.get_submission(db, file.attached_id)
        if submission is not None and submission.status != "in_progress":
            raise AppError(409, "files.submission_finished")


# --- limits ----------------------------------------------------------------------


@dataclass(frozen=True)
class EffectiveLimits:
    purpose: str
    max_bytes: int
    allowed_types: tuple[str, ...]
    image: ImagePolicy
    platform: Optional[FileLimit] = None
    organisation: Optional[FileLimit] = None
    question: dict = dc_field(default_factory=dict)


_IMAGE_KEYS = {f for f in ImagePolicy.__dataclass_fields__}
_BOOL = {"true": True, "1": True, "yes": True, "false": False, "0": False, "no": False}


def parse_question_limits(options: Optional[list[str]]) -> dict[str, Any]:
    """Per-question limits from a file question's `options`, written as
    "key=value" entries before questions had `config` (T1.4.1). Still read,
    under the config:

        max_mb=2
        types=application/pdf,image/*
        keep_original=true
        image.max_side=1200   image.quality=85   image.format=jpeg
        image.compress=false  image.thumb_side=0

    Unknown or malformed entries are ignored."""
    out: dict[str, Any] = {"image": {}}
    for entry in options or []:
        if not isinstance(entry, str) or "=" not in entry:
            continue
        key, raw = (part.strip() for part in entry.split("=", 1))
        try:
            if key == "max_mb":
                value = float(raw)
                if value > 0:
                    out["max_bytes"] = int(value * MB)
            elif key == "types":
                types = [t.strip().lower() for t in raw.split(",") if t.strip()]
                if types:
                    out["allowed_types"] = tuple(types)
            elif key == "keep_original" and raw.lower() in _BOOL:
                out["image"]["keep_original"] = _BOOL[raw.lower()]
            elif key.startswith("image."):
                name = key[len("image."):]
                if name in ("compress", "keep_original") and raw.lower() in _BOOL:
                    out["image"][name] = _BOOL[raw.lower()]
                elif name in ("max_side", "quality", "thumb_side"):
                    out["image"][name] = int(raw)
                elif name == "format" and raw in ("webp", "jpeg", "png", "keep"):
                    out["image"][name] = raw
        except ValueError:
            continue
    return out


def question_limits(options: Optional[list[str]], config: Optional[dict]) -> dict[str, Any]:
    """A file question's limits: its legacy `options` entries, then its
    `config` (FileQuestionConfig, validated on write) key by key on top."""
    out = parse_question_limits(options)
    config = config or {}
    if config.get("max_mb"):
        out["max_bytes"] = int(config["max_mb"] * MB)
    types = [t.strip().lower() for t in config.get("allowed_types") or [] if t.strip()]
    if types:
        out["allowed_types"] = tuple(types)
    out["image"].update({k: v for k, v in (config.get("image") or {}).items() if k in _IMAGE_KEYS})
    return out


def _purpose(name: str) -> Purpose:
    purpose = PURPOSES.get(name)
    if purpose is None:
        raise AppError(422, "files.unknown_purpose", name=name)
    return purpose


def effective_limits(
    db: Session,
    *,
    organisation_id: int,
    purpose: str,
    question_options: Optional[list[str]] = None,
    question_config: Optional[dict] = None,
) -> EffectiveLimits:
    """Code default → platform row → organisation row → question (options,
    then config).
    The platform admin sets the defaults (up to the hard cap); the
    organisation and the question can only tighten size and types. Image
    settings are plain overrides at each layer."""
    p = _purpose(purpose)
    max_bytes = int(p.max_mb * MB)
    types = p.allowed_types
    image = asdict(p.image)

    platform, org = repository.limits_for(db, organisation_id=organisation_id, purpose=purpose)
    if platform is not None:
        if platform.max_bytes:
            max_bytes = platform.max_bytes
        if platform.allowed_types:
            types = tuple(platform.allowed_types)
        image.update({k: v for k, v in (platform.image or {}).items() if k in _IMAGE_KEYS})
    if org is not None:
        if org.max_bytes:
            max_bytes = min(max_bytes, org.max_bytes)
        if org.allowed_types:
            types = intersect_types(types, org.allowed_types)
        image.update({k: v for k, v in (org.image or {}).items() if k in _IMAGE_KEYS})

    question = (
        question_limits(question_options, question_config)
        if question_options is not None or question_config
        else {}
    )
    if question.get("max_bytes"):
        max_bytes = min(max_bytes, question["max_bytes"])
    if question.get("allowed_types"):
        types = intersect_types(types, question["allowed_types"])
    image.update(question.get("image", {}))

    max_bytes = min(max_bytes, FilesEnv.FILES_HARD_MAX_MB * MB)
    return EffectiveLimits(purpose, max_bytes, types, ImagePolicy(**image), platform, org, question)


def _check_limits(limits: EffectiveLimits, *, content_type: str, size: int) -> None:
    if size > limits.max_bytes:
        raise CodedHTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"File is too large: the limit is {limits.max_bytes / MB:.1f} MB",
            code="file_too_large",
        )
    if not type_allowed(content_type, limits.allowed_types):
        raise CodedHTTPException(
            status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            f"Files of type {content_type} are not allowed here",
            code="file_type_not_allowed",
        )


def limit_row_read(row: Optional[FileLimit]) -> Optional[dict]:
    if row is None:
        return None
    return {
        "purpose": row.purpose,
        "organisation_id": row.organisation_id,
        "max_mb": round(row.max_bytes / MB, 3) if row.max_bytes else None,
        "allowed_types": row.allowed_types,
        "image": row.image,
        "updated_at": row.updated_at,
    }


def set_limit(
    db: Session, *, actor: EmployeePrincipal, purpose: str, organisation_id: Optional[int], payload: dict
) -> FileLimit:
    """organisation_id None sets the platform default (platform admins only)."""
    _purpose(purpose)
    if organisation_id is None:
        if not actor.is_platform_admin:
            raise AppError(403, "auth.platform_admin_required")
    elif not _can_manage_org(actor, organisation_id):
        raise AppError(403, "files.limits_admin_only")

    hard = FilesEnv.FILES_HARD_MAX_MB
    if payload.get("max_mb") is not None and payload["max_mb"] > hard:
        raise AppError(422, "files.max_over_hard_cap", hard=hard)
    types = payload.get("allowed_types")
    if types is not None:
        types = [t.strip().lower() for t in types if t.strip()]
        if not all(re.fullmatch(r"[a-z0-9.+-]+/([a-z0-9.+-]+|\*)|\*/\*", t) for t in types):
            raise AppError(422, "files.bad_mime_types")

    row = repository.get_limit(db, organisation_id=organisation_id, purpose=purpose)
    if row is None:
        row = FileLimit(organisation_id=organisation_id, purpose=purpose)
    row.max_bytes = int(payload["max_mb"] * MB) if payload.get("max_mb") else None
    row.allowed_types = types or None
    image = {k: v for k, v in (payload.get("image") or {}).items() if v is not None}
    row.image = image or None
    row.updated_by = actor.id
    return repository.save_limit(db, row)


def delete_limit(db: Session, *, actor: EmployeePrincipal, purpose: str, organisation_id: Optional[int]) -> None:
    _purpose(purpose)
    if organisation_id is None:
        if not actor.is_platform_admin:
            raise AppError(403, "auth.platform_admin_required")
    elif not _can_manage_org(actor, organisation_id):
        raise AppError(403, "files.limits_admin_only")
    repository.delete_limits(db, organisation_id=organisation_id, purpose=purpose)


# --- helpers ---------------------------------------------------------------------

_UNSAFE_NAME = re.compile(r"[\x00-\x1f\x7f/\\]+")


def clean_name(name: str) -> str:
    name = _UNSAFE_NAME.sub("_", name).strip().strip(".") or "file"
    return name[:255]


def _extension(name: str) -> str:
    match = re.search(r"\.([A-Za-z0-9]{1,10})$", name)
    return f".{match.group(1).lower()}" if match else ""


def _new_key(organisation_id: int, purpose: str, name: str) -> str:
    return f"org/{organisation_id}/{purpose}/{uuid.uuid4().hex}{_extension(name)}"


def _stem(key: str) -> str:
    return re.sub(r"\.[A-Za-z0-9]{1,10}$", "", key)


def _trash(db: Session, file: StoredFile, *, key: str, content_type: str, provider: str) -> None:
    """Queues stored bytes for deletion by the cleanup job, in the caller's
    transaction: if the transaction rolls back, nothing is deleted."""
    repository.add_file(
        db,
        StoredFile(
            organisation_id=file.organisation_id, purpose=file.purpose, provider=provider,
            key=key, name=file.name, content_type=content_type, size=0,
            status="deleted", deleted_at=_now(),
        ),
    )


def _trash_all(db: Session, file: StoredFile) -> None:
    """Moves every stored object of `file` (variants too) to the trash."""
    for variant in (file.variants or {}).values():
        _trash(db, file, key=variant["key"], content_type=variant["content_type"], provider=file.provider)
    file.variants = None


def _file_question(db: Session, form_id: Optional[int], field_id: Optional[int], organisation_id: Optional[int]):
    """The form and its file question, checked to belong to the organisation.
    The question is looked up as respondents see it: published versions first."""
    from modules.forms import repository as forms_repository
    from modules.forms import service as forms_service

    if form_id is None or field_id is None:
        raise AppError(422, "files.answer_needs_form_and_field")
    form = forms_repository.get_form(db, form_id)
    if form is None or (organisation_id is not None and form.organisation_id != organisation_id):
        raise AppError(404, "forms.not_found")
    field = forms_service.find_published_field(db, form, field_id)
    if field is None or field.type != "file":
        raise AppError(422, "files.not_a_file_question")
    return form, field


def _question_field_for(db: Session, file: StoredFile):
    if file.purpose != "form_answer" or file.form_id is None or file.field_id is None:
        return None
    from modules.forms import repository as forms_repository
    from modules.forms import service as forms_service

    form = forms_repository.get_form(db, file.form_id)
    return forms_service.find_published_field(db, form, file.field_id) if form else None


def _limits(db: Session, *, organisation_id: int, purpose: str, field=None) -> EffectiveLimits:
    if field is None:
        return effective_limits(db, organisation_id=organisation_id, purpose=purpose)
    return effective_limits(
        db, organisation_id=organisation_id, purpose=purpose,
        question_options=list(field.options or []), question_config=field.config,
    )


def limits_for_question(
    db: Session, *, form_id: int, field_id: int, organisation_id: Optional[int]
) -> EffectiveLimits:
    """The limits a file question applies (organisation_id None: any
    organisation, for public respondents whose form was already checked)."""
    form, field = _file_question(db, form_id, field_id, organisation_id)
    return _limits(db, organisation_id=form.organisation_id, purpose="form_answer", field=field)


def limits_for_file(db: Session, file: StoredFile) -> EffectiveLimits:
    return _limits(
        db, organisation_id=file.organisation_id, purpose=file.purpose,
        field=_question_field_for(db, file),
    )


def _signed_upload(file_provider: str, key: str, content_type: str, size: int) -> UploadTarget:
    try:
        return get_storage(file_provider).signed_upload(
            key, content_type=content_type, size=size, expires_in=FilesEnv.FILES_UPLOAD_URL_TTL_SECONDS
        )
    except StorageError as exc:
        logger.error("storage: signed upload failed: {}", exc)
        raise AppError(503, "files.storage_unavailable") from exc


# --- the service -----------------------------------------------------------------


@dataclass
class UploadStart:
    file: StoredFile
    target: UploadTarget
    limits: EffectiveLimits
    # public uploads: the secret the respondent proves ownership with
    file_token: Optional[str] = None


def add(
    db: Session,
    *,
    actor: Actor,
    purpose: str,
    name: str,
    content_type: str,
    size: int,
    form_id: Optional[int] = None,
    field_id: Optional[int] = None,
    organisation_id: Optional[int] = None,
) -> UploadStart:
    """Starts an upload. The file is `pending` until complete() confirms it.
    `organisation_id` only matters for platform admins uploading a logo."""
    p = _purpose(purpose)
    content_type = content_type.split(";")[0].strip().lower()
    name = clean_name(name)
    question_field = None
    token = None

    if isinstance(actor, PublicActor):
        if not p.public:
            raise AppError(403, "files.kind_not_allowed")
        form, field = _file_question(db, actor.form_id, field_id, None)
        organisation_id, form_id = form.organisation_id, form.id
        question_field = field
        token = secrets.token_urlsafe(24)
    else:
        target_org = organisation_id if (organisation_id and actor.is_platform_admin) else actor.organisation_id
        organisation_id = actor.organisation_id
        if purpose == "org_logo":
            organisation_id = target_org
        if purpose == "form_answer":
            form, field = _file_question(db, form_id, field_id, organisation_id)
            question_field = field
        elif purpose == "org_logo":
            if not _can_manage_org(actor, organisation_id):
                raise AppError(403, "files.logo_admin_only")
            form_id = field_id = None

    limits = _limits(db, organisation_id=organisation_id, purpose=purpose, field=question_field)
    _check_limits(limits, content_type=content_type, size=size)

    provider = default_provider_name()
    file = repository.add_file(
        db,
        StoredFile(
            organisation_id=organisation_id, purpose=purpose, provider=provider,
            key=_new_key(organisation_id, purpose, name), name=name,
            content_type=content_type, size=size, status="pending", processing="none",
            owner_employee_id=actor.id if isinstance(actor, EmployeePrincipal) else None,
            owner_token_hash=_hash_token(token) if token else None,
            form_id=form_id, field_id=field_id,
        ),
    )
    target = _signed_upload(provider, file.key, content_type, size)
    db.commit()
    db.refresh(file)
    return UploadStart(file, target, limits, token)


def complete(db: Session, *, file_id: int, actor: Actor) -> StoredFile:
    """Confirms an upload (or a replacement) against what storage really
    holds. Safe to call twice."""
    from modules.events import service as events

    file = repository.get_file(db, file_id, for_update=True)
    if file is None or file.status == "deleted":
        raise _not_found()
    _ensure_same_org(file, actor)
    if not (_is_owner(file, actor) or (file.purpose == "org_logo" and _can_manage_org(actor, file.organisation_id))):
        raise _not_found()

    replacing = file.replacement
    if file.status == "ready" and not replacing:
        return file

    key = replacing["key"] if replacing else file.key
    provider = replacing["provider"] if replacing else file.provider
    content_type = replacing["content_type"] if replacing else file.content_type
    try:
        info = get_storage(provider).head(key, content_type=content_type)
    except StorageError as exc:
        logger.error("storage: head failed for file {}: {}", file.id, exc)
        raise AppError(503, "files.storage_unavailable") from exc
    if info is None:
        raise CodedHTTPException(status.HTTP_409_CONFLICT, "The file hasn't been uploaded yet", code="file_not_uploaded")

    limits = limits_for_file(db, file)
    stored_type = (info.content_type or content_type).split(";")[0].strip().lower()
    problem = None
    if info.size > limits.max_bytes:
        problem = (status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "file_too_large",
                   f"File is too large: the limit is {limits.max_bytes / MB:.1f} MB")
    elif stored_type != content_type or not type_allowed(stored_type, limits.allowed_types):
        problem = (status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "file_type_not_allowed",
                   "The uploaded file's type doesn't match what was declared")
    if problem:
        if replacing:
            # the rejected bytes aren't any row's key: trash them
            _trash(db, file, key=key, content_type=content_type, provider=provider)
            file.replacement = None
        else:
            # the cleanup job deletes the row and its bytes
            file.status = "deleted"
            file.deleted_at = _now()
        db.commit()
        raise CodedHTTPException(problem[0], problem[2], code=problem[1])

    if replacing:
        # same file id; the old bytes (and thumbnail) go to the trash. The
        # row takes the new key first, so the trash row can hold the old one.
        old_key, old_type, old_provider = file.key, file.content_type, file.provider
        file.key, file.provider = key, provider
        file.name, file.content_type = replacing["name"], content_type
        file.replacement = None
        file.width = file.height = None
        db.flush()
        _trash(db, file, key=old_key, content_type=old_type, provider=old_provider)
        _trash_all(db, file)

    file.size = info.size
    file.checksum = info.etag
    file.status = "ready"
    file.completed_at = _now()
    process = content_type in images.PROCESSABLE and not limits.image.keep_original
    file.processing = "pending" if process else "none"
    events.emit(
        db, "file.uploaded", aggregate_type="file", aggregate_id=file.id,
        organisation_id=file.organisation_id,
        payload={"file_id": file.id, "purpose": file.purpose, "content_type": file.content_type,
                 "size": file.size, "form_id": file.form_id, "field_id": file.field_id,
                 "replaced": bool(replacing)},
    )
    db.commit()
    db.refresh(file)
    return file


def update(
    db: Session, *, file_id: int, actor: Actor, name: str, content_type: str, size: int
) -> UploadStart:
    """Replaces the content. Until complete() confirms the new upload, the
    old content stays in place and keeps working."""
    file = repository.get_file(db, file_id, for_update=True)
    if file is None:
        raise _not_found()
    _ensure_can_modify(db, file, actor)
    if file.status != "ready":
        raise AppError(409, "files.only_finished_replaced")
    content_type = content_type.split(";")[0].strip().lower()
    name = clean_name(name)
    limits = limits_for_file(db, file)
    _check_limits(limits, content_type=content_type, size=size)

    if file.replacement:  # an earlier replacement that never completed
        _trash(db, file, key=file.replacement["key"], content_type=file.replacement["content_type"],
               provider=file.replacement["provider"])
    provider = default_provider_name()
    key = _new_key(file.organisation_id, file.purpose, name)
    file.replacement = {"key": key, "name": name, "content_type": content_type, "size": size,
                        "provider": provider, "requested_at": _now().isoformat()}
    target = _signed_upload(provider, key, content_type, size)
    db.commit()
    db.refresh(file)
    return UploadStart(file, target, limits)


def rename(db: Session, *, file_id: int, actor: Actor, name: str) -> StoredFile:
    file = repository.get_file(db, file_id)
    if file is None:
        raise _not_found()
    _ensure_can_modify(db, file, actor)
    file.name = clean_name(name)
    db.commit()
    db.refresh(file)
    return file


def delete(db: Session, *, file_id: int, actor: Actor) -> None:
    file = repository.get_file(db, file_id, for_update=True)
    if file is None:
        raise _not_found()
    _ensure_can_modify(db, file, actor)
    if file.attached_type == "organisation":
        from modules.organisations.model import Organisation

        org = db.get(Organisation, file.attached_id)
        if org is not None and org.logo_file_id == file.id:
            org.logo_file_id = None
    if file.replacement:
        _trash(db, file, key=file.replacement["key"], content_type=file.replacement["content_type"],
               provider=file.replacement["provider"])
        file.replacement = None
    file.status = "deleted"
    file.deleted_at = _now()
    db.commit()
    purge_deleted(db, limit=20)  # best effort now; the cleanup job catches the rest


def get(db: Session, *, file_id: int, actor: Actor) -> StoredFile:
    file = repository.get_file(db, file_id)
    if file is None:
        raise _not_found()
    _ensure_can_view(db, file, actor)
    return file


def list_files(
    db: Session,
    *,
    actor: EmployeePrincipal,
    purpose: Optional[str],
    attached_type: Optional[str],
    attached_id: Optional[int],
    limit: int,
    offset: int,
) -> tuple[list[StoredFile], int]:
    """Admins see the organisation's files; others see their own, or the
    files of one record they can see (attached_type + attached_id)."""
    owner = None
    if attached_type == "submission" and attached_id is not None:
        from modules.submissions import service as submissions_service

        # raises 403/404 unless the caller can see that submission
        submissions_service.get_submission(db, submission_id=attached_id, principal=actor)
    elif not (actor.is_admin or actor.is_platform_admin) and purpose != "org_logo":
        owner = actor.id
    return repository.list_files(
        db, organisation_id=actor.organisation_id, purpose=purpose, attached_type=attached_type,
        attached_id=attached_id, owner_employee_id=owner, limit=limit, offset=offset,
    )


def link(
    db: Session, *, file_id: int, actor: Actor, variant: Optional[str] = None, inline: bool = False
) -> tuple[str, datetime]:
    file = get(db, file_id=file_id, actor=actor)
    return signed_link_for(file, variant=variant, inline=inline)


def signed_link_for(file: StoredFile, *, variant: Optional[str] = None, inline: bool = False) -> tuple[str, datetime]:
    """A link for a file the caller has already been allowed to see."""
    key, content_type = file.key, file.content_type
    if variant:
        found = (file.variants or {}).get(variant)
        if not found:
            raise AppError(404, "files.no_variant", variant=variant)
        key, content_type = found["key"], found["content_type"]
    ttl = PURPOSES[file.purpose].link_ttl_seconds or FilesEnv.FILES_LINK_TTL_SECONDS
    # images may show inline; anything else always downloads, so a file can
    # never run as a page from a link
    inline = inline and content_type.startswith("image/")
    try:
        url = get_storage(file.provider).signed_link(
            key, download_name=file.name, content_type=content_type, expires_in=ttl, inline=inline
        )
    except StorageError as exc:
        raise AppError(503, "files.storage_unavailable") from exc
    return url, _now() + timedelta(seconds=ttl)


def attach(db: Session, file: StoredFile, *, attached_type: str, attached_id: int) -> None:
    """Ties a ready file to a record. No commit: part of the caller's change."""
    if attached_type not in PURPOSES[file.purpose].attach_types:
        raise AppError(422, "files.wrong_attachment", purpose=file.purpose, attached_type=attached_type)
    if file.status != "ready":
        raise AppError(409, "files.not_uploaded_yet")
    if file.attached_type is not None and (file.attached_type, file.attached_id) != (attached_type, attached_id):
        raise AppError(409, "files.used_elsewhere")
    file.attached_type, file.attached_id = attached_type, attached_id


def detach(db: Session, file: StoredFile) -> None:
    file.attached_type = file.attached_id = None


def discard(db: Session, file: StoredFile) -> None:
    """Deletes a file as part of the caller's change (no commit)."""
    file.status = "deleted"
    file.deleted_at = _now()


def delete_for_form(db: Session, form_id: int) -> int:
    """Every file uploaded for a form's questions (no commit)."""
    return repository.mark_deleted_for_form(db, form_id, _now())


def delete_attached(db: Session, *, attached_type: str, attached_ids: list[int]) -> int:
    """Deletes every file attached to these records (no commit): the cleanup
    job removes the stored bytes once the caller commits."""
    return repository.mark_deleted_for(db, attached_type, attached_ids, _now())


def put_bytes(
    db: Session,
    *,
    organisation_id: int,
    purpose: str,
    name: str,
    content_type: str,
    data: bytes,
    owner_employee_id: Optional[int] = None,
) -> StoredFile:
    """Stores bytes the server made (exports...). The file is ready at once;
    attach it, or the cleanup job deletes it like any unused upload."""
    _purpose(purpose)
    name = clean_name(name)
    provider = default_provider_name()
    key = _new_key(organisation_id, purpose, name)
    try:
        info = get_storage(provider).put_bytes(key, data, content_type=content_type)
    except StorageError as exc:
        raise AppError(503, "files.storage_unavailable") from exc
    file = repository.add_file(
        db,
        StoredFile(
            organisation_id=organisation_id, purpose=purpose, provider=provider, key=key, name=name,
            content_type=content_type, size=info.size, checksum=info.etag, status="ready",
            processing="none", owner_employee_id=owner_employee_id, completed_at=_now(),
        ),
    )
    db.commit()
    db.refresh(file)
    return file


# --- form answers ----------------------------------------------------------------


def load_answer_files(db: Session, values: list) -> dict[int, StoredFile]:
    """The files these answer values name, in one query. A value without a
    usable file_id is skipped here; resolve_answer_file rejects it as before."""
    ids = []
    for value in values:
        try:
            ids.append(int(value["file_id"]))
        except (KeyError, TypeError, ValueError):
            continue
    return repository.get_files(db, ids)


def resolve_answer_file(
    db: Session,
    *,
    form_id: int,
    organisation_id: int,
    field_id: int,
    value: dict,
    actor: Actor,
    submission_id: Optional[int],
    preloaded: Optional[dict[int, StoredFile]] = None,
) -> tuple[StoredFile, dict]:
    """Checks a file answer ({"file_id", "token"?}) and returns the file with
    the value to store: {file_id, name, content_type, size}. `preloaded`
    (from load_answer_files) saves a query per answer."""
    file_id = int(value["file_id"])
    file = preloaded.get(file_id) if preloaded is not None else repository.get_file(db, file_id)
    usable = (
        file is not None
        and file.status == "ready"
        and file.purpose == "form_answer"
        and file.organisation_id == organisation_id
        and file.form_id == form_id
        and file.field_id == field_id
    )
    if usable:
        owner_actor = actor
        if isinstance(actor, PublicActor):
            owner_actor = PublicActor(form_id=actor.form_id, token=value.get("token"))
        usable = _is_owner(file, owner_actor) and (
            file.attached_type is None or (file.attached_type, file.attached_id) == ("submission", submission_id)
        )
    if not usable:
        raise CodedHTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            "An uploaded file is missing or can't be used for this question; upload it again",
            code="file_answer_invalid",
        )
    return file, {"file_id": file.id, "name": file.name, "content_type": file.content_type, "size": file.size}


# --- background work ---------------------------------------------------------------


def purge_deleted(db: Session, *, limit: Optional[int] = None) -> int:
    """Deletes the stored bytes of deleted, abandoned and unused files, then
    their rows. A file whose bytes can't be deleted now stays for next time."""
    now = _now()
    candidates = repository.cleanup_candidates(
        db,
        pending_before=now - timedelta(minutes=FilesEnv.FILES_PENDING_TTL_MINUTES),
        unattached_before=now - timedelta(hours=FilesEnv.FILES_UNATTACHED_TTL_HOURS),
        limit=limit or FilesEnv.FILES_CLEANUP_BATCH_SIZE,
    )
    removed = 0
    for file in candidates:
        try:
            storage = get_storage(file.provider)
            storage.delete(file.key, content_type=file.content_type)
            for variant in (file.variants or {}).values():
                storage.delete(variant["key"], content_type=variant["content_type"])
            if file.replacement:
                storage.delete(file.replacement["key"], content_type=file.replacement["content_type"])
        except StorageError as exc:
            logger.warning("files cleanup: couldn't delete {} yet: {}", file.key, exc)
            continue
        repository.delete_file_row(db, file)
        removed += 1
    db.commit()
    return removed


def clear_stale_replacements(db: Session) -> int:
    """Replacement uploads that never completed: forget them, trash their bytes."""
    from sqlalchemy import DateTime, cast, select

    cutoff = _now() - timedelta(minutes=FilesEnv.FILES_PENDING_TTL_MINUTES)
    # only stale ones, oldest first: a batch of recent replacements can't
    # keep older stale ones from ever being reached
    requested_at = cast(StoredFile.replacement["requested_at"].astext, DateTime(timezone=True))
    rows = db.execute(
        select(StoredFile)
        .where(StoredFile.replacement.is_not(None), requested_at < cutoff)
        .order_by(requested_at, StoredFile.id)
        .limit(FilesEnv.FILES_CLEANUP_BATCH_SIZE)
    ).scalars().all()
    cleared = 0
    for file in rows:
        if not file.replacement:
            continue
        requested = datetime.fromisoformat(file.replacement.get("requested_at", _now().isoformat()))
        if requested < cutoff:
            _trash(db, file, key=file.replacement["key"], content_type=file.replacement["content_type"],
                   provider=file.replacement["provider"])
            file.replacement = None
            cleared += 1
    db.commit()
    return cleared


@dataclass(frozen=True)
class StoredObject:
    provider: str
    key: str
    content_type: str


def stored_objects_of_organisations(db: Session, organisation_ids: list[int]) -> list[StoredObject]:
    """Every stored object of these organisations' files (variants and
    pending replacements too). Collect them before deleting an organisation:
    its file rows go with it, and with them the only record of the keys."""
    out = []
    for file in repository.files_of_organisations(db, organisation_ids):
        out.append(StoredObject(file.provider, file.key, file.content_type))
        for variant in (file.variants or {}).values():
            out.append(StoredObject(file.provider, variant["key"], variant["content_type"]))
        if file.replacement:
            r = file.replacement
            out.append(StoredObject(r["provider"], r["key"], r["content_type"]))
    return out


def delete_stored_objects(objects: list[StoredObject]) -> int:
    """Deletes stored bytes directly. Call after the commit that removed
    their rows. Failures are logged; returns how many were deleted."""
    deleted = 0
    for obj in objects:
        try:
            get_storage(obj.provider).delete(obj.key, content_type=obj.content_type)
            deleted += 1
        except StorageError as exc:
            logger.error("files: could not delete {} ({}); remove it by hand: {}", obj.key, obj.provider, exc)
    return deleted


def cleanup(db: Session) -> dict[str, int]:
    return {"replacements": clear_stale_replacements(db), "purged": purge_deleted(db)}


def process_image(db: Session, file_id: int) -> str:
    """Server-side compression and thumbnail for a just-uploaded image. Runs
    in the outbox relay's transaction (no commit). Returns what happened."""
    file = repository.get_file(db, file_id, for_update=True)
    if file is None or file.status != "ready" or file.processing != "pending":
        return "nothing to do"
    policy = limits_for_file(db, file).image
    storage = get_storage(file.provider)
    data = storage.get_bytes(file.key, max_bytes=FilesEnv.FILES_HARD_MAX_MB * MB, content_type=file.content_type)

    try:
        processed = images.compress(data, policy)
        source = processed.data if processed else data
        thumb = images.thumbnail(source, policy.thumb_side) if policy.thumb_side else None
    except images.ImageError as exc:
        logger.warning("file {}: image not processed: {}", file.id, exc)
        file.processing = "failed"
        return "unreadable image"

    stem = _stem(file.key)
    if processed:
        new_key = f"{stem}-c.{processed.extension}"
        info = storage.put_bytes(new_key, processed.data, content_type=processed.content_type)
        old_key, old_type = file.key, file.content_type
        file.key, file.content_type, file.size, file.checksum = new_key, processed.content_type, info.size, info.etag
        db.flush()
        _trash(db, file, key=old_key, content_type=old_type, provider=file.provider)
        file.name = re.sub(r"\.[A-Za-z0-9]{1,10}$", "", file.name) + f".{processed.extension}"
        file.width, file.height = processed.width, processed.height
    else:
        try:
            file.width, file.height = images.dimensions(data)
        except images.ImageError:
            pass
    if thumb:
        thumb_key = f"{stem}-t.webp"
        info = storage.put_bytes(thumb_key, thumb.data, content_type=thumb.content_type)
        file.variants = {**(file.variants or {}), "thumb": {
            "key": thumb_key, "content_type": thumb.content_type, "size": info.size,
            "width": thumb.width, "height": thumb.height}}
    file.processing = "done" if processed or thumb else "skipped"
    return "compressed" if processed else ("thumbnail only" if thumb else "kept as is")
