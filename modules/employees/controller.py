from sqlalchemy.orm import Session

from common.dto import Page

from . import service
from .dto import EmployeeCreate, EmployeeRead, EmployeeSummary, EmployeeUpdate


def list_employees(
    db: Session,
    *,
    organisation_id: int,
    assigned_unit_ids: list[int],
    limit: int,
    offset: int,
) -> Page[EmployeeSummary]:
    items, total = service.list_employees(
        db,
        organisation_id=organisation_id,
        assigned_unit_ids=assigned_unit_ids,
        limit=limit,
        offset=offset,
    )
    summaries: list[EmployeeSummary] = []
    for e in items:
        summary = EmployeeSummary.model_validate(e)
        summary.role_name = e.role.name if e.role else None
        summary.unit_name = e.unit.name if e.unit else None
        summaries.append(summary)
    return Page(items=summaries, total=total, limit=limit, offset=offset)


def get_employee(
    db: Session, employee_id: int, organisation_id: int, assigned_unit_ids: list[int]
) -> EmployeeRead:
    return EmployeeRead.model_validate(
        service.get_employee(db, employee_id, organisation_id, assigned_unit_ids)
    )


def create_employee(
    db: Session, payload: EmployeeCreate, organisation_id: int, assigned_unit_ids: list[int]
) -> EmployeeRead:
    return EmployeeRead.model_validate(
        service.create_employee(
            db, payload=payload, organisation_id=organisation_id, assigned_unit_ids=assigned_unit_ids
        )
    )


def update_employee(
    db: Session,
    employee_id: int,
    payload: EmployeeUpdate,
    organisation_id: int,
    assigned_unit_ids: list[int],
) -> EmployeeRead:
    return EmployeeRead.model_validate(
        service.update_employee(
            db,
            employee_id=employee_id,
            payload=payload,
            organisation_id=organisation_id,
            assigned_unit_ids=assigned_unit_ids,
        )
    )


def delete_employee(
    db: Session, employee_id: int, organisation_id: int, assigned_unit_ids: list[int]
) -> None:
    service.delete_employee(
        db, employee_id=employee_id, organisation_id=organisation_id, assigned_unit_ids=assigned_unit_ids
    )
