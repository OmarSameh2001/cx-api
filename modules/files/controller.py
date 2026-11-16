from dataclasses import asdict
from typing import Optional

from sqlalchemy.orm import Session

from common.dto import Page
from config import FilesEnv
from modules.auth.dto import EmployeePrincipal

from . import service
from .dto import (
    EffectiveLimitsRead,
    FileLinkResponse,
    FileRead,
    ImagePolicyRead,
    LimitRead,
    LimitWrite,
    PublicUploadRequest,
    UploadRequest,
    UploadStartResponse,
    UploadTargetRead,
)
from .model import StoredFile
from .purposes import MB


def file_read(file: StoredFile) -> FileRead:
    read = FileRead.model_validate(file)
    read.has_thumbnail = bool((file.variants or {}).get("thumb"))
    return read


def _start_response(start: service.UploadStart) -> UploadStartResponse:
    t = start.target
    return UploadStartResponse(
        file=file_read(start.file),
        upload=UploadTargetRead(method=t.method, url=t.url, headers=t.headers, fields=t.fields, expires_at=t.expires_at),
        image=ImagePolicyRead(**asdict(start.limits.image)),
        file_token=start.file_token,
    )


def start_upload(db: Session, payload: UploadRequest, actor: EmployeePrincipal) -> UploadStartResponse:
    return _start_response(service.add(
        db, actor=actor, purpose=payload.purpose, name=payload.name, content_type=payload.content_type,
        size=payload.size, form_id=payload.form_id, field_id=payload.field_id,
        organisation_id=payload.organisation_id,
    ))


def start_public_upload(db: Session, form_id: int, payload: PublicUploadRequest) -> UploadStartResponse:
    return _start_response(service.add(
        db, actor=service.PublicActor(form_id=form_id), purpose="form_answer", name=payload.name,
        content_type=payload.content_type, size=payload.size, field_id=payload.field_id,
    ))


def complete_upload(db: Session, file_id: int, actor: service.Actor) -> FileRead:
    return file_read(service.complete(db, file_id=file_id, actor=actor))


def replace_content(db: Session, file_id: int, payload, actor: EmployeePrincipal) -> UploadStartResponse:
    return _start_response(service.update(
        db, file_id=file_id, actor=actor, name=payload.name, content_type=payload.content_type, size=payload.size,
    ))


def rename(db: Session, file_id: int, name: str, actor: EmployeePrincipal) -> FileRead:
    return file_read(service.rename(db, file_id=file_id, actor=actor, name=name))


def delete(db: Session, file_id: int, actor: EmployeePrincipal) -> None:
    service.delete(db, file_id=file_id, actor=actor)


def get(db: Session, file_id: int, actor: EmployeePrincipal) -> FileRead:
    return file_read(service.get(db, file_id=file_id, actor=actor))


def list_files(db: Session, *, actor, purpose, attached_type, attached_id, limit, offset) -> Page[FileRead]:
    items, total = service.list_files(
        db, actor=actor, purpose=purpose, attached_type=attached_type,
        attached_id=attached_id, limit=limit, offset=offset,
    )
    return Page[FileRead](items=[file_read(f) for f in items], total=total, limit=limit, offset=offset)


def link(db: Session, file_id: int, actor, *, variant: Optional[str], inline: bool) -> FileLinkResponse:
    url, expires_at = service.link(db, file_id=file_id, actor=actor, variant=variant, inline=inline)
    return FileLinkResponse(url=url, expires_at=expires_at)


def _limits_read(limits: service.EffectiveLimits, *, with_layers: bool) -> EffectiveLimitsRead:
    platform = service.limit_row_read(limits.platform) if with_layers else None
    org = service.limit_row_read(limits.organisation) if with_layers else None
    return EffectiveLimitsRead(
        purpose=limits.purpose,
        max_bytes=limits.max_bytes,
        max_mb=round(limits.max_bytes / MB, 3),
        allowed_types=list(limits.allowed_types),
        image=ImagePolicyRead(**asdict(limits.image)),
        hard_max_mb=FilesEnv.FILES_HARD_MAX_MB,
        platform=LimitRead(**platform) if platform else None,
        organisation=LimitRead(**org) if org else None,
    )


def question_limits(db: Session, *, form_id: int, field_id: int, actor: EmployeePrincipal) -> EffectiveLimitsRead:
    limits = service.limits_for_question(db, form_id=form_id, field_id=field_id, organisation_id=actor.organisation_id)
    return _limits_read(limits, with_layers=False)


def public_question_limits(db: Session, *, form_id: int, field_id: int) -> EffectiveLimitsRead:
    limits = service.limits_for_question(db, form_id=form_id, field_id=field_id, organisation_id=None)
    return _limits_read(limits, with_layers=False)


def effective_limits(db: Session, *, purpose: str, actor: EmployeePrincipal, organisation_id: Optional[int]) -> EffectiveLimitsRead:
    org_id = organisation_id if (organisation_id and actor.is_platform_admin) else actor.organisation_id
    limits = service.effective_limits(db, organisation_id=org_id, purpose=purpose)
    platform = service.limit_row_read(limits.platform)
    org = service.limit_row_read(limits.organisation)
    return EffectiveLimitsRead(
        purpose=purpose,
        max_bytes=limits.max_bytes,
        max_mb=round(limits.max_bytes / MB, 3),
        allowed_types=list(limits.allowed_types),
        image=ImagePolicyRead(**asdict(limits.image)),
        hard_max_mb=FilesEnv.FILES_HARD_MAX_MB,
        platform=LimitRead(**platform) if platform else None,
        organisation=LimitRead(**org) if org else None,
    )


def set_limit(db: Session, *, purpose: str, payload: LimitWrite, actor: EmployeePrincipal,
              organisation_id: Optional[int]) -> LimitRead:
    row = service.set_limit(
        db, actor=actor, purpose=purpose, organisation_id=organisation_id,
        payload=payload.model_dump(exclude_unset=False),
    )
    return LimitRead(**service.limit_row_read(row))


def delete_limit(db: Session, *, purpose: str, actor: EmployeePrincipal, organisation_id: Optional[int]) -> None:
    service.delete_limit(db, actor=actor, purpose=purpose, organisation_id=organisation_id)
