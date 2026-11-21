import copy
import secrets
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import HTTPException, status
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from common.errors import CodedHTTPException
from modules.auth.dto import EmployeePrincipal
from modules.events import service as events
from modules.units import repository as units_repository

from . import access, repository
from .dto import (
    LEGACY_SETTING_KEYS,
    FormCreate,
    FormFieldCreate,
    FormSettings,
    FormSettingsPatch,
    FormSettingsRead,
    FormUpdate,
    FormVersionDiff,
    DiffItem,
    DiffPart,
)
from .model import SNAPSHOT_FIELD_ATTRS, Form, FormVersion, PublishedForm, VersionField


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


def _ensure_creator(form: Form, employee_id: int) -> None:
    if form.created_by != employee_id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Only the form creator can modify it"
        )


def _ensure_creator_can_delete(form: Form, employee_id: int) -> None:
    _ensure_creator(form, employee_id)
    if form.is_active:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Form must be inactive to be deleted"
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


def get_form_for_employee(db: Session, form_id: int, employee: EmployeePrincipal) -> Form:
    """The form as the editor and reviewers read it. Respondents get theirs
    through their in-progress submission instead (without the answers)."""
    form = get_form(db, form_id, organisation_id=employee.organisation_id)
    if not access.can_read_form(employee, form):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed to view this form")
    return form


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
    employee: EmployeePrincipal,
    is_active: Optional[bool],
    is_archived: Optional[bool],
    submitter_type: Optional[str],
    created_by: Optional[int],
    name: Optional[str],
    form_type: Optional[str],
    limit: int,
    offset: int,
) -> tuple[list[Form], int]:
    organisation_id = employee.organisation_id
    if not access.can_read_all_forms(employee):
        # Without a form permission the only forms you can open are your own,
        # so those are all that's listed; asking for someone else's is empty.
        # Forms to answer come from /forms/assigned-to-me instead.
        if created_by not in (None, employee.id):
            return [], 0
        created_by = employee.id
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


def _ensure_units_in_organisation(db: Session, unit_ids, organisation_id: int) -> None:
    """A form can only be targeted at units of its own organisation."""
    wanted = list(dict.fromkeys(unit_ids or []))
    found = units_repository.unit_ids_in_organisation(db, wanted, organisation_id)
    for unit_id in wanted:  # the first missing one, in the order sent
        if unit_id not in found:
            raise HTTPException(status.HTTP_404_NOT_FOUND, f"Unit {unit_id} not found")


# --- versions (E1.5) ----------------------------------------------------------
# The form row's fields and sections are the draft. Publishing freezes them
# into a FormVersion; respondents, scoring and submission views use the
# version a submission was started on. Name, description, settings, audience
# and status stay live on the form. The type can't change once published.


def snapshot_of(form: Form) -> dict:
    """The draft's structure, as a version stores it."""
    return {
        "type": form.type,
        "sections": copy.deepcopy(form.sections),
        "fields": [
            {attr: copy.deepcopy(getattr(f, attr)) for attr in SNAPSHOT_FIELD_ATTRS}
            for f in sorted(form.fields, key=lambda f: (f.order, f.id or 0))
        ],
    }


_SECTION_DEFAULTS = {
    "title": None, "description": None, "order": 0, "score_weight": 1.0, "next_section_id": None,
}


def _section(s: dict) -> dict:
    """A section with its defaults filled in, so one stored before a key
    existed compares equal to the same section saved again."""
    return {"id": s["id"], **{k: s.get(k, d) for k, d in _SECTION_DEFAULTS.items()}}


def _comparable(snapshot: dict) -> dict:
    """A snapshot without what doesn't change what respondents get: field
    ids (a question restored from an old version gets a new id)."""
    return {
        "type": snapshot.get("type"),
        "sections": sorted((_section(s) for s in snapshot.get("sections") or []), key=lambda s: s["id"]),
        "fields": sorted(
            ({k: v for k, v in f.items() if k != "id"} for f in snapshot.get("fields") or []),
            key=lambda f: f.get("key") or "",
        ),
    }


def has_unpublished_changes(form: Form) -> bool:
    version = form.current_version
    if version is None:
        return True
    return _comparable(snapshot_of(form)) != _comparable(version.snapshot or {})


def published(form: Form) -> Optional[PublishedForm]:
    """The form as respondents get it now, or None before its first publish."""
    if form.current_version is None:
        return None
    return PublishedForm(form, form.current_version)


def as_answered(submission) -> "Form | PublishedForm":
    """The form a submission is checked, scored and shown against: the version
    it was started on. Rows from before versions fall back to the current one."""
    if submission.form_version is not None:
        return PublishedForm(submission.form, submission.form_version)
    return published(submission.form) or submission.form


def find_published_field(db: Session, form: Form, field_id: int):
    """A question by id, as respondents may be answering it: the current
    version first, then older ones (an attempt started before a publish),
    then the draft (the builder previewing a question's limits)."""
    view = published(form)
    for f in view.fields if view else []:
        if f.id == field_id:
            return f
    for version in repository.list_versions(db, form.id):
        if form.current_version_id == version.id:
            continue
        for f in (version.snapshot or {}).get("fields") or []:
            if f.get("id") == field_id:
                return VersionField.from_snapshot(f)
    return next((f for f in form.fields if f.id == field_id), None)


def _publish(db: Session, form: Form, employee_id: Optional[int]) -> FormVersion:
    """New version from the draft, made current, with its event. No commit."""
    version = repository.add_version(db, form, snapshot=snapshot_of(form), published_by=employee_id)
    events.emit(
        db,
        "form.published",
        aggregate_type="form",
        aggregate_id=form.id,
        organisation_id=form.organisation_id,
        payload={
            "form_id": form.id, "type": form.type, "public": bool(form.public_token),
            "version_id": version.id, "version": version.number,
        },
    )
    return version


def publish_form(db: Session, *, form_id: int, employee: EmployeePrincipal) -> Form:
    form = get_form(db, form_id, organisation_id=employee.organisation_id)
    if not access.can_manage_form(employee, form):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed to publish this form")
    if not has_unpublished_changes(form):
        raise CodedHTTPException(
            status.HTTP_409_CONFLICT, "The draft has no changes to publish", code="nothing_to_publish"
        )
    _publish(db, form, employee.id)
    db.commit()
    db.refresh(form)
    return form


def list_versions(db: Session, *, form_id: int, employee: EmployeePrincipal) -> list[dict]:
    form = get_form_for_employee(db, form_id, employee)
    counts = repository.count_submissions_by_version(db, form.id)
    return [
        {
            "id": v.id, "number": v.number, "published_at": v.published_at,
            "published_by": v.published_by,
            "question_count": len((v.snapshot or {}).get("fields") or []),
            "submission_count": counts.get(v.id, 0),
        }
        for v in repository.list_versions(db, form.id)
    ]


def get_version(
    db: Session, *, form_id: int, number: int, employee: EmployeePrincipal
) -> tuple[Form, FormVersion]:
    form = get_form_for_employee(db, form_id, employee)
    version = repository.get_version(db, form.id, number)
    if version is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Version not found")
    return form, version


_DIFF_QUESTION_ATTRS = tuple(a for a in SNAPSHOT_FIELD_ATTRS if a not in ("id", "key"))
def _section_changes(a: dict, b: dict) -> list[str]:
    return [k for k, d in _SECTION_DEFAULTS.items() if a.get(k, d) != b.get(k, d)]


def _diff(old: Optional[dict], new: dict) -> tuple[DiffPart, DiffPart]:
    """Questions are matched by key, sections by id. Only which attributes
    changed is listed; the values are in the versions themselves."""
    old = old or {}
    before = {f.get("key"): f for f in old.get("fields") or []}
    after = {f.get("key"): f for f in new.get("fields") or []}
    changed = []
    for k, f in after.items():
        if k in before:
            names = [a for a in _DIFF_QUESTION_ATTRS if before[k].get(a) != f.get(a)]
            if names:
                changed.append(DiffItem(ref=k, label=f["question"], changes=names))
    questions = DiffPart(
        added=[DiffItem(ref=k, label=f["question"]) for k, f in after.items() if k not in before],
        removed=[DiffItem(ref=k, label=f["question"]) for k, f in before.items() if k not in after],
        changed=changed,
    )
    s_before = {s["id"]: s for s in old.get("sections") or []}
    s_after = {s["id"]: s for s in new.get("sections") or []}
    s_changed = []
    for i, sec in s_after.items():
        if i in s_before:
            names = _section_changes(s_before[i], sec)
            if names:
                s_changed.append(DiffItem(ref=i, label=sec.get("title", ""), changes=names))
    sections = DiffPart(
        added=[DiffItem(ref=i, label=x.get("title", "")) for i, x in s_after.items() if i not in s_before],
        removed=[DiffItem(ref=i, label=x.get("title", "")) for i, x in s_before.items() if i not in s_after],
        changed=s_changed,
    )
    return questions, sections


def diff_version(
    db: Session, *, form_id: int, number: int, against: Optional[str], employee: EmployeePrincipal
) -> FormVersionDiff:
    """What version `number` changed from the one before it (or from
    version `against`), or, with against="draft", what the draft changes on
    top of it."""
    form, version = get_version(db, form_id=form_id, number=number, employee=employee)
    if against == "draft":
        questions, sections = _diff(version.snapshot, snapshot_of(form))
        return FormVersionDiff(from_number=number, to="draft", questions=questions, sections=sections)
    if against is not None:
        if not against.isdigit():
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY, 'against must be a version number or "draft"'
            )
        base = repository.get_version(db, form.id, int(against))
        if base is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Version not found")
    else:
        base = repository.get_version(db, form.id, number - 1) if number > 1 else None
    questions, sections = _diff(base.snapshot if base else None, version.snapshot)
    return FormVersionDiff(
        from_number=base.number if base else None, to=number, questions=questions, sections=sections
    )


def restore_version(db: Session, *, form_id: int, number: int, employee: EmployeePrincipal) -> Form:
    """Replaces the draft's structure with a version's. Nothing changes for
    respondents until the draft is published."""
    form = get_form(db, form_id, organisation_id=employee.organisation_id)
    _ensure_creator(form, employee.id)
    version = repository.get_version(db, form.id, number)
    if version is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Version not found")
    snapshot = copy.deepcopy(version.snapshot or {})
    fields = [
        {k: v for k, v in f.items() if k in SNAPSHOT_FIELD_ATTRS}
        for f in snapshot.get("fields") or []
    ]
    return repository.restore_draft(db, form, sections=snapshot.get("sections"), fields=fields)


def _field_rows(fields: list[FormFieldCreate]) -> list[dict]:
    """Field payloads as repository rows. An existing field sent without
    `config` keeps its config, so a client that doesn't know about config
    can't wipe it."""
    rows = []
    for f in fields:
        row = f.model_dump()
        if f.id is not None and "config" not in f.model_fields_set:
            row.pop("config")
        rows.append(row)
    return rows


def _merged_settings(form: Form, patch: FormSettingsPatch) -> dict:
    current = FormSettingsRead.model_validate(form.settings or {}).model_dump()
    merged = {**current, **patch.model_dump(exclude_unset=True)}
    try:
        return FormSettings.model_validate(merged).model_dump()
    except ValidationError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY, f"Invalid settings: {exc.errors()[0]['msg']}"
        ) from None


def create_form(db: Session, *, payload: FormCreate, employee: EmployeePrincipal) -> Form:
    _ensure_units_in_organisation(db, payload.assigned_to_units, employee.organisation_id)
    data = payload.model_dump(exclude={"fields", *LEGACY_SETTING_KEYS})
    data["organisation_id"] = employee.organisation_id
    if _should_have_public_token(payload):
        data["public_token"] = _new_public_token()
    fields = _field_rows(payload.fields)
    validate_branching(payload.type, data.get("sections"), fields)
    # an active form is live from creation: version 1 is published with it
    publish = data.get("is_active", True)
    return repository.create_form(
        db, data=data, fields=fields, created_by=employee.id,
        before_commit=(lambda form: _publish(db, form, employee.id)) if publish else None,
    )


_COPIED_FORM_ATTRS = (
    "source_type",
    "type",
    "description",
    "submitter_type",
    "assigned_to_units",
    "settings",
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
    "config",
)


def duplicate_form(db: Session, *, form_id: int, employee: EmployeePrincipal) -> Form:
    """A fresh, unpublished copy of the draft, with no responses or versions."""
    form = get_form(db, form_id, organisation_id=employee.organisation_id)
    if not access.can_manage_form(employee, form):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed to duplicate this form")

    data = {key: copy.deepcopy(getattr(form, key)) for key in _COPIED_FORM_ATTRS}
    data["name"] = f"{form.name[:248]} (copy)"
    data["organisation_id"] = employee.organisation_id
    # the copy has no responses whose results could be revealed
    data["settings"] = {**(data["settings"] or {}), "results_revealed": False}
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
    if not access.can_manage_form(employee, form):
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
    if not access.can_manage_form(employee, form):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed to manage this form")
    return repository.set_public_token(db, form, None)


def update_form(
    db: Session, *, form_id: int, payload: FormUpdate, employee: EmployeePrincipal
) -> Form:
    """Edits the draft. Respondents keep the published version until the
    draft is published (or the form is activated), so responses lock nothing:
    their submissions stay tied to the version they answered."""
    form = get_form(db, form_id, organisation_id=employee.organisation_id)
    _ensure_creator(form, employee.id)
    _ensure_known_field_ids(form, payload)
    if payload.type is not None and payload.type != form.type and form.current_version_id is not None:
        raise CodedHTTPException(
            status.HTTP_409_CONFLICT,
            "A published form can't change its type; duplicate it instead",
            code="form_type_locked",
        )

    data = payload.model_dump(exclude_unset=True, exclude={"fields"})
    if "assigned_to_units" in data:
        _ensure_units_in_organisation(db, data["assigned_to_units"], employee.organisation_id)
    if payload.sections is not None:
        # exclude_unset is recursive; store sections with their defaults filled in
        data["sections"] = [s.model_dump() for s in payload.sections]
    if "settings" in data:
        if payload.settings is None:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "settings can't be null")
        data["settings"] = _merged_settings(form, payload.settings)
    fields = _field_rows(payload.fields) if payload.fields is not None else None
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
    _ensure_creator_can_delete(form, employee.id)
    responses = CodedHTTPException(
        status.HTTP_409_CONFLICT,
        "This form has responses, so it can't be deleted. Archive it instead.",
        code="form_has_submissions",
    )
    if repository.form_has_submissions(db, form.id):
        raise responses
    from modules.files import service as files

    # the files cleanup job removes their stored bytes; this is rolled back
    # with everything else if the delete fails
    files.delete_for_form(db, form.id)
    # drafts go with the form; a response submitted since the check above
    # still blocks the delete at the foreign key
    if not repository.delete_form(db, form):
        raise responses


def toggle_active(
    db: Session, *, form_id: int, active: bool, employee: EmployeePrincipal
) -> Form:
    form = get_form(db, form_id, organisation_id=employee.organisation_id)
    if not access.can_manage_form(employee, form):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed to modify this form")
    if active and has_unpublished_changes(form):
        # going live means going live with the draft
        _publish(db, form, employee.id)
    form.is_active = active
    db.commit()
    db.refresh(form)
    return form


def reveal_form_results(
    db: Session, *, form_id: int, employee: EmployeePrincipal
) -> Form:
    form = get_form(db, form_id, organisation_id=employee.organisation_id)
    if not access.can_review(employee, form):
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

    filters = dict(
        organisation_id=employee.organisation_id,
        submitter_type=employee.principal,
        unit_ids=unit_ids,
        name=name,
        form_type=form_type,
    )
    if my_status:
        # my_status is worked out per form below, not in SQL, so filtering by
        # it pages over every assigned form; paging first would return short
        # pages and a total that ignores the filter
        forms = repository.list_forms_assigned(db, **filters, limit=None, offset=0)
        total = None
    else:
        forms = repository.list_forms_assigned(db, **filters, limit=limit, offset=offset)
        total = repository.count_forms_assigned(db, **filters)

    if not forms:
        return [], total or 0

    form_ids = [f.id for f in forms]
    # only what the status needs, not the answers
    rows = db.execute(
        select(
            Submission.form_id, Submission.status, Submission.expires_at, Submission.submitted_at
        ).where(
            Submission.form_id.in_(form_ids),
            Submission.user_id == employee.id,
        )
    ).all()

    by_form: dict[int, list] = {}
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

    if my_status:
        return items[offset:offset + limit], len(items)
    return items, total
