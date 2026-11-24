from sqlalchemy.orm import Session

from modules.auth.dto import EmployeePrincipal

from . import service
from .dto import AuditCatalogue, AuditPage, AuditQuery


def list_events(db: Session, payload: AuditQuery, employee: EmployeePrincipal) -> AuditPage:
    return service.query(db, organisation_id=employee.organisation_id, payload=payload)


def list_platform_events(db: Session, payload: AuditQuery) -> AuditPage:
    return service.query(db, organisation_id=None, payload=payload)


def catalogue() -> AuditCatalogue:
    return service.catalogue()


def record_history(
    db: Session, employee: EmployeePrincipal, entity_type: str, entity_id: int, cursor, limit: int
) -> AuditPage:
    return service.record_history(db, employee=employee, entity_type=entity_type, entity_id=entity_id,
                                  cursor=cursor, limit=limit)
