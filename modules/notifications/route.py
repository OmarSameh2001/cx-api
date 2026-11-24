from typing import Optional

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy.orm import Session

from db import get_db
from modules.auth.dto import EmployeePrincipal
from modules.auth.route import current_employee

from . import controller
from .dto import ChannelsInfo, Locale, MarkedRead, NotificationPage, TestRequest, TestResult, UnreadCount

router = APIRouter(prefix="/notifications", tags=["notifications"])

# Each person's own bell: no permission is needed, and only the caller's own
# notifications are ever read or changed.


@router.get("", response_model=NotificationPage)
def list_mine(
    before_id: Optional[int] = Query(default=None, ge=1),
    limit: int = Query(default=20, ge=1, le=100),
    unread_only: bool = False,
    locale: Optional[Locale] = None,
    accept_language: Optional[str] = Header(default=None),
    db: Session = Depends(get_db),
    employee: EmployeePrincipal = Depends(current_employee),
):
    """Newest first, rendered in `locale` (else the browser language)."""
    return controller.list_mine(db, employee, before_id=before_id, limit=limit, unread_only=unread_only,
                                locale=locale or accept_language)


@router.get("/unread-count", response_model=UnreadCount)
def unread_count(db: Session = Depends(get_db), employee: EmployeePrincipal = Depends(current_employee)):
    return controller.unread_count(db, employee)


@router.post("/read-all", response_model=MarkedRead)
def mark_all_read(db: Session = Depends(get_db), employee: EmployeePrincipal = Depends(current_employee)):
    return controller.mark_all_read(db, employee)


@router.post("/{notification_id}/read", response_model=MarkedRead)
def mark_read(
    notification_id: int, db: Session = Depends(get_db), employee: EmployeePrincipal = Depends(current_employee)
):
    return controller.mark_read(db, employee, notification_id)


@router.post("/{notification_id}/unread", response_model=MarkedRead)
def mark_unread(
    notification_id: int, db: Session = Depends(get_db), employee: EmployeePrincipal = Depends(current_employee)
):
    return controller.mark_unread(db, employee, notification_id)


# --- organisation admins ------------------------------------------------------------


@router.get("/channels", response_model=ChannelsInfo)
def channels(employee: EmployeePrincipal = Depends(current_employee)):
    """Which channels are on, and the providers each tries in order."""
    return controller.channels(employee)


@router.post("/test", response_model=TestResult)
def send_test(
    payload: TestRequest, db: Session = Depends(get_db), employee: EmployeePrincipal = Depends(current_employee)
):
    """Sends the caller a test notification on each channel, straight away."""
    return controller.send_test(db, employee, payload)
