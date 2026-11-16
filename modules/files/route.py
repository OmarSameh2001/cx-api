from typing import Literal, Optional

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from common.dto import Page
from db import get_db
from modules.auth.dto import EmployeePrincipal
from modules.auth.route import current_employee

from . import controller
from .dto import (
    EffectiveLimitsRead,
    FileLinkResponse,
    FileRead,
    LimitRead,
    LimitWrite,
    PurposeName,
    RenameRequest,
    ReplaceRequest,
    UploadRequest,
    UploadStartResponse,
)

# Uploads go straight from the browser to storage:
#   1. POST /files/uploads             -> a file id and a signed upload target
#   2. the browser sends the bytes to upload.url
#   3. POST /files/{id}/complete       -> checked against storage, now usable
# Public-form respondents use /public/forms/{token}/uploads instead.
router = APIRouter(prefix="/files", tags=["files"])


@router.post("/uploads", response_model=UploadStartResponse, status_code=status.HTTP_201_CREATED)
def start_upload(
    payload: UploadRequest,
    db: Session = Depends(get_db),
    employee: EmployeePrincipal = Depends(current_employee),
):
    return controller.start_upload(db, payload, employee)


@router.get("/limits/question", response_model=EffectiveLimitsRead)
def get_question_limits(
    form_id: int = Query(...),
    field_id: int = Query(...),
    db: Session = Depends(get_db),
    employee: EmployeePrincipal = Depends(current_employee),
):
    """What one file question accepts, and how the browser should compress
    images for it, before anything is uploaded."""
    return controller.question_limits(db, form_id=form_id, field_id=field_id, actor=employee)


@router.get("/limits/{purpose}", response_model=EffectiveLimitsRead)
def get_limits(
    purpose: PurposeName,
    organisation_id: Optional[int] = Query(default=None, description="platform admins: another organisation"),
    db: Session = Depends(get_db),
    employee: EmployeePrincipal = Depends(current_employee),
):
    return controller.effective_limits(db, purpose=purpose, actor=employee, organisation_id=organisation_id)


@router.put("/limits/{purpose}", response_model=LimitRead)
def set_limits(
    purpose: PurposeName,
    payload: LimitWrite,
    scope: Literal["organisation", "platform"] = Query(default="organisation"),
    organisation_id: Optional[int] = Query(default=None, description="platform admins: another organisation"),
    db: Session = Depends(get_db),
    employee: EmployeePrincipal = Depends(current_employee),
):
    """scope=platform sets the default for every organisation (platform
    admins); scope=organisation tightens it for one organisation (its admin)."""
    org_id = None if scope == "platform" else (organisation_id or employee.organisation_id)
    return controller.set_limit(db, purpose=purpose, payload=payload, actor=employee, organisation_id=org_id)


@router.delete("/limits/{purpose}", status_code=status.HTTP_204_NO_CONTENT)
def delete_limits(
    purpose: PurposeName,
    scope: Literal["organisation", "platform"] = Query(default="organisation"),
    organisation_id: Optional[int] = Query(default=None),
    db: Session = Depends(get_db),
    employee: EmployeePrincipal = Depends(current_employee),
):
    org_id = None if scope == "platform" else (organisation_id or employee.organisation_id)
    controller.delete_limit(db, purpose=purpose, actor=employee, organisation_id=org_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("", response_model=Page[FileRead])
def list_files(
    purpose: Optional[PurposeName] = Query(default=None),
    attached_type: Optional[Literal["submission", "organisation"]] = Query(default=None),
    attached_id: Optional[int] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    employee: EmployeePrincipal = Depends(current_employee),
):
    return controller.list_files(
        db, actor=employee, purpose=purpose, attached_type=attached_type,
        attached_id=attached_id, limit=limit, offset=offset,
    )


@router.get("/{file_id}", response_model=FileRead)
def get_file(file_id: int, db: Session = Depends(get_db), employee: EmployeePrincipal = Depends(current_employee)):
    return controller.get(db, file_id, employee)


@router.post("/{file_id}/complete", response_model=FileRead)
def complete_upload(file_id: int, db: Session = Depends(get_db), employee: EmployeePrincipal = Depends(current_employee)):
    return controller.complete_upload(db, file_id, employee)


@router.put("/{file_id}/content", response_model=UploadStartResponse)
def replace_content(
    file_id: int,
    payload: ReplaceRequest,
    db: Session = Depends(get_db),
    employee: EmployeePrincipal = Depends(current_employee),
):
    """Replace the bytes: upload to the returned target, then POST complete."""
    return controller.replace_content(db, file_id, payload, employee)


@router.patch("/{file_id}", response_model=FileRead)
def rename_file(
    file_id: int,
    payload: RenameRequest,
    db: Session = Depends(get_db),
    employee: EmployeePrincipal = Depends(current_employee),
):
    return controller.rename(db, file_id, payload.name, employee)


@router.delete("/{file_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_file(file_id: int, db: Session = Depends(get_db), employee: EmployeePrincipal = Depends(current_employee)):
    controller.delete(db, file_id, employee)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/{file_id}/link", response_model=FileLinkResponse)
def file_link(
    file_id: int,
    variant: Optional[Literal["thumb"]] = Query(default=None),
    inline: bool = Query(default=False, description="images only: show instead of download"),
    db: Session = Depends(get_db),
    employee: EmployeePrincipal = Depends(current_employee),
):
    return controller.link(db, file_id, employee, variant=variant, inline=inline)
