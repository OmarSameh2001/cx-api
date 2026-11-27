"""Who may read one record's history: anyone who may open the record.

Each kind of record is checked with its own module's read rules (the same
functions its GET endpoint uses), so a record the caller can't open is 404
or 403 here too. Returns the organisation the record belongs to, which the
history is then limited to, and which entries must not show their values.

The modules are imported inside the functions: they import the audit
service themselves, to record their changes.
"""

from dataclasses import dataclass
from typing import Callable

from sqlalchemy.orm import Session

from common.errors import AppError
from modules.auth.dto import EmployeePrincipal


@dataclass(frozen=True)
class RecordAccess:
    organisation_id: int
    # entries of these actions are listed, but their values are not shown
    masked_actions: frozenset[str] = frozenset()


def _require(employee: EmployeePrincipal, permission: str) -> None:
    if not employee.is_admin and permission not in (employee.permissions or []):
        raise AppError(403, "auth.permissions_missing", missing=permission)


def _role(db: Session, employee: EmployeePrincipal, record_id: int) -> RecordAccess:
    from modules.roles import service

    _require(employee, "roles:read")
    return RecordAccess(service.get_role(db, record_id, employee.organisation_id).organisation_id)


def _employee(db: Session, employee: EmployeePrincipal, record_id: int) -> RecordAccess:
    from modules.employees import service

    _require(employee, "employees:read")
    found = service.get_employee(db, record_id, employee.organisation_id, employee.assigned_unit_ids)
    return RecordAccess(found.organisation_id)


def _unit(db: Session, employee: EmployeePrincipal, record_id: int) -> RecordAccess:
    from modules.units import service

    _require(employee, "units:read")
    return RecordAccess(service.get_unit(db, record_id, employee.organisation_id).organisation_id)


def _form(db: Session, employee: EmployeePrincipal, record_id: int) -> RecordAccess:
    from modules.forms import access, service

    form = service.get_form_for_employee(db, record_id, employee)
    # readers who may not see correct answers (respondents with forms:read)
    # see that the answer key changed, not what it changed to
    masked = frozenset() if access.can_see_answers(employee, form) else frozenset({"form.answer_key_changed"})
    return RecordAccess(form.organisation_id, masked)


def _organisation(db: Session, employee: EmployeePrincipal, record_id: int) -> RecordAccess:
    from modules.organisations import service

    return RecordAccess(service.get_organisation(db, record_id, viewer=employee).id)


CHECKS: dict[str, Callable[[Session, EmployeePrincipal, int], RecordAccess]] = {
    "role": _role,
    "employee": _employee,
    "unit": _unit,
    "form": _form,
    "organisation": _organisation,
}


def check(db: Session, employee: EmployeePrincipal, entity_type: str, record_id: int) -> RecordAccess:
    rule = CHECKS.get(entity_type)
    if rule is None:
        raise AppError(404, "audit.no_history", entity_type=entity_type)
    return rule(db, employee, record_id)
