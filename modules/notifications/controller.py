from typing import Optional

from sqlalchemy.orm import Session

from modules.auth.dto import EmployeePrincipal

from . import service
from .dto import ChannelsInfo, MarkedRead, NotificationPage, TestRequest, TestResult, UnreadCount


def list_mine(
    db: Session, employee: EmployeePrincipal, *, before_id: Optional[int], limit: int, unread_only: bool,
    locale: Optional[str],
) -> NotificationPage:
    return service.list_mine(db, employee=employee, before_id=before_id, limit=limit,
                             unread_only=unread_only, locale=locale)


def unread_count(db: Session, employee: EmployeePrincipal) -> UnreadCount:
    return UnreadCount(unread=service.unread_count(db, employee=employee))


def mark_read(db: Session, employee: EmployeePrincipal, notification_id: int) -> MarkedRead:
    return service.mark_read(db, employee=employee, ids=[notification_id])


def mark_unread(db: Session, employee: EmployeePrincipal, notification_id: int) -> MarkedRead:
    return service.mark_unread(db, employee=employee, notification_id=notification_id)


def mark_all_read(db: Session, employee: EmployeePrincipal) -> MarkedRead:
    return service.mark_read(db, employee=employee, ids=None)


def channels(employee: EmployeePrincipal) -> ChannelsInfo:
    return service.channels(employee)


def send_test(db: Session, employee: EmployeePrincipal, payload: TestRequest) -> TestResult:
    return service.send_test(db, employee=employee, payload=payload)
