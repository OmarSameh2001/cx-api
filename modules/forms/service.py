import copy
import secrets
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from common.errors import CodedHTTPException
from modules.auth.dto import EmployeePrincipal

from . import repository
from .dto import FormCreate, FormUpdate
from .model import Form


def _new_public_token() -> str:
    return secrets.token_urlsafe(16)


def _should_have_public_token(form_or_data) -> bool:
    """Public token applies to questionnaires that accept customers."""
    type_ = getattr(form_or_data, "type", None) or (
        form_or_data.get("type") if isinstance(form_or_data, dict) else None
    )
    submitter = getattr(form_or_data, "submitter_type", None) or (
        form_or_data.get("submitter_type") if isinstance(form_or_data, dict) else None
    )
    return type_ == "questionnaire" and "customer" in (submitter or [])


def _ensure_creator_can_edit(form: Form, employee_id: int) -> None:
    if form.created_by != employee_id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Only the form creator can modify it"
        )
    if form.is_active:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Form must be inactive to be modified"
        )


def ordered_sections(sections: list[dict]) -> list[dict]:
    """Canonical section order, shared by branching validation and the
    submission path walk so both agree on what "forward" means."""
    return sorted(sections, key=lambda s: (s.get("order", 0), s["id"]))


def branch_key(field_type: str, value: Any) -> str:
    """Normalise an answer (or a branching key) so they compare the same way
    _correctness_fraction compares answers."""
    key = str(value).strip()
    return key.lower() if field_type == "boolean" else key


_STRUCTURAL_FIELD_ATTRS = ("type", "options", "right_answer", "score_weight", "section_id", "branching")
_STRUCTURAL_SECTION_KEYS = ("order", "score_weight", "next_section_id")


def _ensure_known_field_ids(form: Form, payload: FormUpdate) -> None:
    if payload.fields is None:
        return
    ids = [f.id for f in payload.fields if f.id is not None]
    if len(ids) != len(set(ids)):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "Duplicate field ids")
    own_ids = {f.id for f in form.fields}
    foreign = [i for i in ids if i not in own_ids]
    if foreign:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"Field ids do not belong to this form: {foreign}",
        )


def _structure_changed(form: Form, payload: FormUpdate) -> bool:
    """True if the update changes anything that would invalidate existing
    submissions. Wording, help text, field order and is_required are safe."""
    if payload.type is not None and payload.type != form.type:
        return True

    if payload.fields is not None:
        existing = {f.id: f for f in form.fields}
        sent_ids = [f.id for f in payload.fields]
        if None in sent_ids or set(sent_ids) != set(existing):
            return True
        for f in payload.fields:
            obj = existing[f.id]
            for attr in _STRUCTURAL_FIELD_ATTRS:
                if getattr(f, attr) != getattr(obj, attr):
                    return True

    if "sections" in payload.model_fields_set:
        current = {s["id"]: s for s in (form.sections or [])}
        sent = payload.sections or []
        if {s.id for s in sent} != set(current):
            return True
        defaults = {"order": 0, "score_weight": 1.0, "next_section_id": None}
        for s in sent:
            old = current[s.id]
            for key in _STRUCTURAL_SECTION_KEYS:
                if getattr(s, key) != old.get(key, defaults[key]):
                    return True
    return False


def validate_branching(
    form_type: str, sections: Optional[list[dict]], fields: list[dict]
) -> None:
    """Public because the AI form generator runs it too, so a draft it returns
    is one create_form accepts.

    Branching rules must target a later section (or "end"), so a path can
    never loop. Only questionnaires with sections can branch."""
    sections = sections or []
    has_rules = any(f.get("branching") for f in fields) or any(
        s.get("next_section_id") is not None for s in sections
    )
    if not has_rules:
        return

    def fail(msg: str):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, msg)

    if form_type == "exam":
        fail("Branching is only supported on questionnaires")
    if not sections:
        fail("Branching requires the form to have sections")

    position = {s["id"]: i for i, s in enumerate(ordered_sections(sections))}
    if len(position) != len(sections):
        fail("Duplicate section ids")

    def check_target(source_id: int, target) -> None:
        if target == "end":
            return
        if target not in position:
            fail(f"Branching targets unknown section {target}")
        if position[target] <= position[source_id]:
            fail(f"Section {source_id} can only jump forward, not to section {target}")

    branching_sections: set[int] = set()
    for f in fields:
        if not f.get("branching"):
            continue
        sid = f.get("section_id")
        if sid not in position:
            fail("Branching questions must belong to a section")
        if sid in branching_sections:
            fail(f"Section {sid} can only have one branching question")
        branching_sections.add(sid)
        for target in f["branching"].values():
            check_target(sid, target)

    for s in sections:
        if s.get("next_section_id") is not None:
            check_target(s["id"], s["next_section_id"])


def has_submissions(db: Session, form: Form) -> bool:
    return repository.form_has_submissions(db, form.id)


def _ensure_same_org(form: Form, organisation_id: int) -> None:
    if form.organisation_id != organisation_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Form not found")


def get_form(db: Session, form_id: int, *, organisation_id: Optional[int] = None) -> Form:
    form = repository.get_form(db, form_id)
    if form is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Form not found")
    if organisation_id is not None:
        _ensure_same_org(form, organisation_id)
    return form


def list_forms(
    db: Session,
    *,
    organisation_id: int,
    is_active: Optional[bool],
    is_archived: Optional[bool],
    submitter_type: Optional[str],
    created_by: Optional[int],
    name: Optional[str],
    form_type: Optional[str],
    limit: int,
    offset: int,
) -> tuple[list[Form], int]:
    items = repository.list_forms(
        db,
        organisation_id=organisation_id,
        is_active=is_active,
        is_archived=is_archived,
        submitter_type=submitter_type,
        created_by=created_by,
        name=name,
        form_type=form_type,
        limit=limit,
        offset=offset,
    )
    total = repository.count_forms(
        db,
        organisation_id=organisation_id,
        is_active=is_active,
        is_archived=is_archived,
        submitter_type=submitter_type,
        created_by=created_by,
        name=name,
        form_type=form_type,
    )
    return items, total


def create_form(db: Session, *, payload: FormCreate, employee: EmployeePrincipal) -> Form:
    data = payload.model_dump(exclude={"fields"})
    data["organisation_id"] = employee.organisation_id
    if _should_have_public_token(payload):
        data["public_token"] = _new_public_token()
    fields = [f.model_dump() for f in payload.fields]
    validate_branching(payload.type, data.get("sections"), fields)
    return repository.create_form(db, data=data, fields=fields, created_by=employee.id)


_COPIED_FORM_ATTRS = (
    "source_type",
    "type",
    "description",
    "submitter_type",
    "assigned_to_units",
    "time_limit_minutes",
    "max_attempts",
    "sections",
)
_COPIED_FIELD_ATTRS = (
    "question",
    "type",
    "options",
    "right_answer",
    "order",
    "help_text",
    "is_required",
    "score_weight",
    "section_id",
    "branching",
)


def duplicate_form(db: Session, *, form_id: int, employee: EmployeePrincipal) -> Form:
    """A fresh copy with no responses: the way to change the structure of a
    form its responses have locked."""
    form = get_form(db, form_id, organisation_id=employee.organisation_id)
    if form.created_by != employee.id and "forms:manage" not in (employee.permissions or []):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed to duplicate this form")

    data = {key: copy.deepcopy(getattr(form, key)) for key in _COPIED_FORM_ATTRS}
    data["name"] = f"{form.name[:248]} (copy)"
    data["organisation_id"] = employee.organisation_id
    # inactive so it can be edited before anyone responds
    data["is_active"] = False
    if _should_have_public_token(data):
        data["public_token"] = _new_public_token()
    fields = [
        {key: copy.deepcopy(getattr(f, key)) for key in _COPIED_FIELD_ATTRS}
        for f in form.fields
    ]
    return repository.create_form(db, data=data, fields=fields, created_by=employee.id)


def rotate_public_token(
    db: Session, *, form_id: int, employee: EmployeePrincipal
) -> Form:
    form = get_form(db, form_id, organisation_id=employee.organisation_id)
    if not (
        form.created_by == employee.id
        or "forms:manage" in (employee.permissions or [])
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed to manage this form")
    if form.type != "questionnaire" or "customer" not in (form.submitter_type or []):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Public link is only available for questionnaires that accept customer submissions",
        )
    return repository.set_public_token(db, form, _new_public_token())


def revoke_public_token(
    db: Session, *, form_id: int, employee: EmployeePrincipal
) -> Form:
    form = get_form(db, form_id, organisation_id=employee.organisation_id)
    if not (
        form.created_by == employee.id
        or "forms:manage" in (employee.permissions or [])
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed to manage this form")
    return repository.set_public_token(db, form, None)


def update_form(
    db: Session, *, form_id: int, payload: FormUpdate, employee: EmployeePrincipal
) -> Form:
    form = get_form(db, form_id, organisation_id=employee.organisation_id)
    _ensure_creator_can_edit(form, employee.id)
    _ensure_known_field_ids(form, payload)
    if _structure_changed(form, payload) and repository.form_has_submissions(db, form.id):
        raise CodedHTTPException(
            status.HTTP_409_CONFLICT,
            "Form has submissions; only wording can be changed "
            "(send each existing field with its id)",
            code="form_has_submissions",
        )

    data = payload.model_dump(exclude_unset=True, exclude={"fields"})
    if payload.sections is not None:
        # exclude_unset is recursive; store sections with their defaults filled in
        data["sections"] = [s.model_dump() for s in payload.sections]
    fields = (
        [f.model_dump() for f in payload.fields] if payload.fields is not None else None
    )
    validate_branching(
        data.get("type") or form.type,
        data["sections"] if "sections" in data else form.sections,
        fields
        if fields is not None
        else [{"section_id": f.section_id, "branching": f.branching} for f in form.fields],
    )
    return repository.update_form(db, form, data=data, fields=fields)


def delete_form(db: Session, *, form_id: int, employee: EmployeePrincipal) -> None:
    form = get_form(db, form_id, organisation_id=employee.organisation_id)
    _ensure_creator_can_edit(form, employee.id)
    repository.delete_form(db, form)


def toggle_active(
    db: Session, *, form_id: int, active: bool, employee: EmployeePrincipal
) -> Form:
    form = get_form(db, form_id, organisation_id=employee.organisation_id)
    if form.created_by != employee.id and "forms:manage" not in (employee.permissions or []):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed to modify this form")
    form.is_active = active
    db.commit()
    db.refresh(form)
    return form


def reveal_form_results(
    db: Session, *, form_id: int, employee: EmployeePrincipal
) -> Form:
    form = get_form(db, form_id, organisation_id=employee.organisation_id)
    if form.created_by != employee.id and "submissions:view" not in (employee.permissions or []):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed to reveal results")
    form.results_revealed = True
    db.commit()
    db.refresh(form)
    return form


def list_assigned_to_me(
    db: Session,
    *,
    employee: EmployeePrincipal,
    limit: int,
    offset: int,
    my_status: Optional[str] = None,
    name: Optional[str] = None,
    form_type: Optional[str] = None,
) -> tuple[list[dict], int]:
    """Return forms targeted to the caller's unit set, enriched with my_status."""
    from modules.submissions.model import Submission

    unit_ids: list[int] = list(employee.assigned_unit_ids or [])
    if employee.unit_id is not None and employee.unit_id not in unit_ids:
        unit_ids.append(employee.unit_id)

    forms = repository.list_forms_assigned(
        db,
        organisation_id=employee.organisation_id,
        submitter_type=employee.principal,
        unit_ids=unit_ids,
        name=name,
        form_type=form_type,
        limit=limit,
        offset=offset,
    )
    total = repository.count_forms_assigned(
        db,
        organisation_id=employee.organisation_id,
        submitter_type=employee.principal,
        unit_ids=unit_ids,
        name=name,
        form_type=form_type,
    )

    if not forms:
        return [], total

    form_ids = [f.id for f in forms]
    rows = db.execute(
        select(Submission).where(
            Submission.form_id.in_(form_ids),
            Submission.user_id == employee.id,
        )
    ).scalars().all()

    by_form: dict[int, list[Submission]] = {}
    for s in rows:
        by_form.setdefault(s.form_id, []).append(s)

    now = datetime.now(timezone.utc)
    items: list[dict] = []
    for form in forms:
        subs = by_form.get(form.id, [])
        finalized = [s for s in subs if s.status in ("submitted", "late")]
        open_sub = next((s for s in subs if s.status == "in_progress"), None)
        if open_sub and form.type == "exam" and open_sub.expires_at and open_sub.expires_at < now:
            my_status_val = "expired"
        elif open_sub:
            my_status_val = "in_progress"
        elif finalized:
            last = max(finalized, key=lambda s: s.submitted_at or datetime.min)
            my_status_val = last.status
        elif any(s.status == "expired" for s in subs):
            my_status_val = "expired"
        else:
            my_status_val = "not_started"

        if my_status and my_status_val != my_status:
            continue

        items.append(
            {
                "id": form.id,
                "name": form.name,
                "type": form.type,
                "is_active": form.is_active,
                "is_archived": form.is_archived,
                "submitter_type": form.submitter_type or [],
                "time_limit_minutes": form.time_limit_minutes,
                "max_attempts": form.max_attempts,
                "results_revealed": form.results_revealed,
                "created_at": form.created_at,
                "created_by": form.created_by,
                "my_status": my_status_val,
                "attempts_used": len(finalized),
            }
        )

    return items, total
