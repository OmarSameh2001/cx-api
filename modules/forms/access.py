"""Who may read a form, and who may see its correct answers.

Seeded permissions are `resource:read/create/update/delete`; `forms:manage`
and `submissions:view` are older names some roles may still carry by hand, so
both spellings are honoured.
"""

from modules.auth.dto import EmployeePrincipal

from .model import Form

_MANAGE_PERMISSIONS = {"forms:update", "forms:manage"}
_REVIEW_PERMISSIONS = {"submissions:read", "submissions:view"}
# managing the form or reviewing its submissions means seeing the answers
_ANSWER_PERMISSIONS = _MANAGE_PERMISSIONS | _REVIEW_PERMISSIONS


def _holds(employee: EmployeePrincipal, wanted: set[str]) -> bool:
    return employee.is_admin or bool(wanted & set(employee.permissions or []))


def can_manage_form(employee: EmployeePrincipal, form: Form) -> bool:
    """Activate, duplicate, manage the public link (editing stays creator-only)."""
    return form.created_by == employee.id or _holds(employee, _MANAGE_PERMISSIONS)


def can_review_all(employee: EmployeePrincipal) -> bool:
    """Review every submission in the organisation."""
    return _holds(employee, _REVIEW_PERMISSIONS)


def can_review(employee: EmployeePrincipal, form: Form) -> bool:
    """Review this form's submissions (and reveal their results)."""
    return form.created_by == employee.id or can_review_all(employee)


def can_see_answers(employee: EmployeePrincipal, form: Form) -> bool:
    return form.created_by == employee.id or _holds(employee, _ANSWER_PERMISSIONS)


def can_read_all_forms(employee: EmployeePrincipal) -> bool:
    """Open any form in the organisation, not just your own."""
    return _holds(employee, _ANSWER_PERMISSIONS | {"forms:read"})


def can_read_form(employee: EmployeePrincipal, form: Form) -> bool:
    """Read the form itself. Respondents don't need this: they get their
    questions through their own in-progress submission."""
    return can_see_answers(employee, form) or "forms:read" in (employee.permissions or [])
