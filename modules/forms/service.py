import copy
import secrets
from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import status
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from common.errors import AppError, CodedHTTPException
from modules.audit import service as audit
from modules.auth.dto import EmployeePrincipal
from modules.events import service as events
from modules.units import repository as units_repository

from . import access, repository
from .dto import (
    LEGACY_SETTING_KEYS,
    media_ids_in_config,
    media_ids_in_theme,
    FormCreate,
    FormFieldCreate,
    FormSettings,
    FormSettingsPatch,
    FormSettingsRead,
    FormUpdate,
    FormVersionDiff,
    DiffItem,
    PrefillLinkCreate,
    PrefillLinkRead,
    stored_settings,
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
        raise AppError(403, "forms.creator_only")


def _ensure_creator_can_delete(form: Form, employee_id: int) -> None:
    _ensure_creator(form, employee_id)
    if form.is_active:
        raise AppError(409, "forms.must_be_inactive")


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
        raise AppError(422, "forms.duplicate_fields")
    own_ids = {f.id for f in form.fields}
    foreign = [i for i in ids if i not in own_ids]
    if foreign:
        raise AppError(422, "forms.foreign_fields", foreign=foreign)


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

    def fail(code: str, **params):
        raise AppError(422, code, **params)

    if form_type == "exam":
        fail("forms.branching_questionnaires_only")
    if not sections:
        fail("forms.branching_needs_sections")

    position = {s["id"]: i for i, s in enumerate(ordered_sections(sections))}
    if len(position) != len(sections):
        fail("forms.duplicate_section_ids")

    def check_target(source_id: int, target) -> None:
        if target == "end":
            return
        if target not in position:
            fail("forms.branching_unknown_target", target=target)
        if position[target] <= position[source_id]:
            fail("forms.branching_backwards", source=source_id, target=target)

    branching_sections: set[int] = set()
    for f in fields:
        if not f.get("branching"):
            continue
        sid = f.get("section_id")
        if sid not in position:
            fail("forms.branching_outside_section")
        if sid in branching_sections:
            fail("forms.branching_one_per_section", section=sid)
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
        raise AppError(404, "forms.not_found")


def get_form_for_employee(db: Session, form_id: int, employee: EmployeePrincipal) -> Form:
    """The form as the editor and reviewers read it. Respondents get theirs
    through their in-progress submission instead (without the answers)."""
    form = get_form(db, form_id, organisation_id=employee.organisation_id)
    if not access.can_read_form(employee, form):
        raise AppError(403, "forms.view_denied")
    return form


def get_form(db: Session, form_id: int, *, organisation_id: Optional[int] = None) -> Form:
    form = repository.get_form(db, form_id)
    if form is None:
        raise AppError(404, "forms.not_found")
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
            raise AppError(404, "units.id_not_found", unit_id=unit_id)


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


_ANSWER_KEY_ATTRS = ("right_answer", "score_weight")


def _answer_key_changes(old: Optional[dict], new: dict) -> tuple[dict, dict]:
    """What a publish changes in how answers are scored: correct answers and
    weights of questions that were already in the previous version (matched
    by key), and section weights. ({change-log entries}, {key: question})."""
    if not old:
        return {}, {}
    changes: dict[str, Any] = {}
    labels: dict[str, str] = {}
    before = {f.get("key"): f for f in old.get("fields") or []}
    for f in new.get("fields") or []:
        prev = before.get(f.get("key"))
        if prev is None:
            continue
        for attr in _ANSWER_KEY_ATTRS:
            if prev.get(attr) != f.get(attr):
                changes[f"{f['key']}.{attr}"] = [audit.value(prev.get(attr)), audit.value(f.get(attr))]
                labels[f["key"]] = audit.value(f.get("question") or "")
    s_before = {s["id"]: s for s in old.get("sections") or []}
    for sec in new.get("sections") or []:
        prev = s_before.get(sec["id"])
        if prev is not None and prev.get("score_weight", 1.0) != sec.get("score_weight", 1.0):
            changes[f"section_{sec['id']}.score_weight"] = [
                prev.get("score_weight", 1.0), sec.get("score_weight", 1.0),
            ]
    return changes, labels


def _record_publish(db: Session, form: Form, previous: Optional[dict], version: FormVersion) -> None:
    questions, sections = _diff(previous, version.snapshot)
    audit.record(db, "form.published", entity=form, data={
        "version": version.number,
        "questions_added": len(questions.added),
        "questions_removed": len(questions.removed),
        "questions_changed": len(questions.changed),
        "sections_changed": len(sections.added) + len(sections.removed) + len(sections.changed),
    })
    changes, labels = _answer_key_changes(previous, version.snapshot)
    if changes:
        audit.record(db, "form.answer_key_changed", entity=form, changes=changes,
                     data={"version": version.number, "questions": labels})


def _publish(db: Session, form: Form, employee_id: Optional[int]) -> FormVersion:
    """New version from the draft, made current, with its event. No commit."""
    previous = form.current_version.snapshot if form.current_version is not None else None
    version = repository.add_version(db, form, snapshot=snapshot_of(form), published_by=employee_id)
    _record_publish(db, form, previous, version)
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
        raise AppError(403, "forms.publish_denied")
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
        raise AppError(404, "forms.version_not_found")
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
            raise AppError(422, "forms.bad_compare_target")
        base = repository.get_version(db, form.id, int(against))
        if base is None:
            raise AppError(404, "forms.version_not_found")
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
        raise AppError(404, "forms.version_not_found")
    snapshot = copy.deepcopy(version.snapshot or {})
    fields = [
        {k: v for k, v in f.items() if k in SNAPSHOT_FIELD_ATTRS}
        for f in snapshot.get("fields") or []
    ]
    # saved by restore_draft's commit, or rolled back with it
    audit.record(db, "form.version_restored", entity=form, data={"version": number})
    return repository.restore_draft(db, form, sections=snapshot.get("sections"), fields=fields)


# --- pictures (E2.1) -------------------------------------------------------------


def _media_ids(fields, settings: Optional[dict]) -> set[int]:
    """File ids of the pictures these fields (rows or objects) and settings name."""
    ids: set[int] = set()
    for f in fields or []:
        config = f.get("config") if isinstance(f, dict) else getattr(f, "config", None)
        ids |= media_ids_in_config(config)
    return ids | media_ids_in_theme((settings or {}).get("theme"))


def media_for(db: Session, form, *, with_theme: bool = True) -> dict[str, str]:
    """Links to the pictures a form (a Form, a PublishedForm or a version's
    fields) shows, by file id."""
    from modules.files import service as files

    ids = _media_ids(form.fields, {"theme": form.theme} if with_theme else None)
    return files.media_links(db, organisation_id=form.organisation_id, file_ids=ids)


def _use_media(db: Session, form: Form, ids: set[int]) -> None:
    from modules.files import service as files

    files.use_form_media(db, form_id=form.id, organisation_id=form.organisation_id, file_ids=ids)


def _remap_media(value: Any, copies: dict[int, int]) -> Any:
    """`value` with every picture reference pointing at its copy."""
    if isinstance(value, dict):
        out = {k: _remap_media(v, copies) for k, v in value.items()}
        if isinstance(out.get("file_id"), int) and out["file_id"] in copies:
            out["file_id"] = copies[out["file_id"]]
        return out
    if isinstance(value, list):
        return [_remap_media(v, copies) for v in value]
    return value


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
        return stored_settings(FormSettings.model_validate(merged))
    except ValidationError as exc:
        raise AppError(422, "forms.invalid_settings", error=exc.errors()[0]['msg']) from None


def _ensure_settings_people(db: Session, settings: dict, organisation_id: int) -> None:
    """Everyone a form notifies (T2.2.3) works in the form's organisation."""
    ids = ((settings or {}).get("notify") or {}).get("employee_ids") or []
    if not ids:
        return
    from modules.employees import repository as employees_repository

    known = employees_repository.ids_in_organisation(db, organisation_id=organisation_id, employee_ids=ids)
    missing = [i for i in ids if i not in known]
    if missing:
        raise AppError(422, "forms.notify_unknown_people", ids=", ".join(map(str, missing)))


def create_form(db: Session, *, payload: FormCreate, employee: EmployeePrincipal) -> Form:
    _ensure_units_in_organisation(db, payload.assigned_to_units, employee.organisation_id)
    data = payload.model_dump(exclude={"fields", *LEGACY_SETTING_KEYS})
    data["settings"] = stored_settings(payload.settings)
    _ensure_settings_people(db, data["settings"], employee.organisation_id)
    data["organisation_id"] = employee.organisation_id
    if _should_have_public_token(payload):
        data["public_token"] = _new_public_token()
    fields = _field_rows(payload.fields)
    validate_branching(payload.type, data.get("sections"), fields)
    # an active form is live from creation: version 1 is published with it
    publish = data.get("is_active", True)

    media = _media_ids(fields, data.get("settings"))

    def before_commit(form: Form) -> None:
        _use_media(db, form, media)
        audit.record_created(db, form)
        if publish:
            _publish(db, form, employee.id)

    return repository.create_form(
        db, data=data, fields=fields, created_by=employee.id, before_commit=before_commit,
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
        raise AppError(403, "forms.duplicate_denied")

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
    # the copy gets its own pictures, so deleting either form keeps the other whole
    media = _media_ids(fields, data["settings"])
    if media:
        from modules.files import service as files

        copies = files.copy_form_media(
            db, organisation_id=employee.organisation_id, file_ids=media, owner_employee_id=employee.id,
        )
        fields = [{**f, "config": _remap_media(f["config"], copies)} for f in fields]
        data["settings"] = _remap_media(data["settings"], copies)
        media = set(copies.values())

    def before_commit(copied: Form) -> None:
        _use_media(db, copied, media)
        audit.record_created(db, copied, data={"copied_from": form.id})

    return repository.create_form(
        db, data=data, fields=fields, created_by=employee.id, before_commit=before_commit,
    )


def rotate_public_token(
    db: Session, *, form_id: int, employee: EmployeePrincipal
) -> Form:
    form = get_form(db, form_id, organisation_id=employee.organisation_id)
    if not access.can_manage_form(employee, form):
        raise AppError(403, "forms.manage_denied")
    if form.type != "questionnaire" or "customer" not in (form.submitter_type or []):
        raise AppError(409, "forms.public_link_unavailable")
    # the token itself is never logged: anyone holding it can answer
    audit.record(db, "form.public_link_rotated", entity=form)
    return repository.set_public_token(db, form, _new_public_token())


def revoke_public_token(
    db: Session, *, form_id: int, employee: EmployeePrincipal
) -> Form:
    form = get_form(db, form_id, organisation_id=employee.organisation_id)
    if not access.can_manage_form(employee, form):
        raise AppError(403, "forms.manage_denied")
    if form.public_token:
        audit.record(db, "form.public_link_revoked", entity=form)
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
            raise AppError(422, "forms.settings_null")
        data["settings"] = _merged_settings(form, payload.settings)
        _ensure_settings_people(db, data["settings"], employee.organisation_id)
    fields = _field_rows(payload.fields) if payload.fields is not None else None
    validate_branching(
        data.get("type") or form.type,
        data["sections"] if "sections" in data else form.sections,
        fields
        if fields is not None
        else [{"section_id": f.section_id, "branching": f.branching} for f in form.fields],
    )
    before = audit.snapshot(form)
    media = _media_ids(fields, data.get("settings"))

    def before_commit(f: Form) -> None:
        _use_media(db, f, media)
        # draft questions are logged when they are published, not on every save
        audit.record_changes(db, f, before)

    return repository.update_form(db, form, data=data, fields=fields, before_commit=before_commit)


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
    # rolled back with the delete if it fails
    audit.record_deleted(db, form)
    # drafts go with the form; a response submitted since the check above
    # still blocks the delete at the foreign key
    if not repository.delete_form(db, form):
        raise responses


def toggle_active(
    db: Session, *, form_id: int, active: bool, employee: EmployeePrincipal
) -> Form:
    form = get_form(db, form_id, organisation_id=employee.organisation_id)
    if not access.can_manage_form(employee, form):
        raise AppError(403, "forms.modify_denied")
    before = audit.snapshot(form)
    if active and has_unpublished_changes(form):
        # going live means going live with the draft
        _publish(db, form, employee.id)
    form.is_active = active
    audit.record_changes(db, form, before, action="form.activated" if active else "form.deactivated")
    db.commit()
    db.refresh(form)
    return form


def reveal_form_results(
    db: Session, *, form_id: int, employee: EmployeePrincipal
) -> Form:
    form = get_form(db, form_id, organisation_id=employee.organisation_id)
    if not access.can_review(employee, form):
        raise AppError(403, "forms.reveal_denied")
    if not form.results_revealed:
        audit.record(db, "form.results_revealed", entity=form)
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

    from sqlalchemy import and_, or_

    from . import behaviour

    form_ids = [f.id for f in forms]
    # an anonymous form's attempts carry the caller's keyed stand-in instead of their id
    keys = [behaviour.respondent_key(fid, "employee", employee.id) for fid in form_ids]
    # only what the status needs, not the answers
    rows = db.execute(
        select(
            Submission.form_id, Submission.status, Submission.expires_at, Submission.submitted_at
        ).where(
            Submission.form_id.in_(form_ids),
            or_(
                Submission.user_id == employee.id,
                and_(Submission.user_id.is_(None), Submission.respondent_key.in_(keys)),
            ),
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


# --- prefilled links (T2.2.7) -------------------------------------------------

MAX_PREFILL_TOKEN_LENGTH = 4000


def create_prefill_link(
    db: Session, *, form_id: int, payload: PrefillLinkCreate, employee: EmployeePrincipal
) -> PrefillLinkRead:
    """Signs hidden values and starting answers for the form's published
    version. Only declared hidden fields may be set, and answers must fit
    their questions (as a draft would)."""
    from datetime import timedelta

    from modules.submissions.answer_rules import validate_answer_values

    from . import behaviour

    form = get_form(db, form_id, organisation_id=employee.organisation_id)
    if not access.can_manage_form(employee, form):
        raise AppError(403, "forms.manage_denied")
    view = published(form)
    if view is None:
        raise AppError(409, "forms.prefill_unpublished")
    declared = {h.key for h in behaviour.settings_of(form).hidden_fields}
    unknown = [k for k in payload.hidden if k not in declared]
    if unknown:
        raise AppError(422, "forms.unknown_hidden_field", key=unknown[0])
    from .dto import DISPLAY_TYPES

    answerable = {str(f.id) for f in view.fields if f.type not in DISPLAY_TYPES}
    stray = [k for k in payload.answers if k not in answerable]
    if stray:
        raise AppError(422, "forms.prefill_unknown_question", id=stray[0])
    validate_answer_values(view, payload.answers, draft=True)
    if any(f.type == "file" and str(f.id) in payload.answers for f in view.fields):
        raise AppError(422, "forms.prefill_file_question")

    expires_at = (
        datetime.now(timezone.utc) + timedelta(days=payload.expires_in_days)
        if payload.expires_in_days else None
    )
    token = behaviour.prefill_token(form.id, hidden=payload.hidden, answers=payload.answers, expires_at=expires_at)
    if len(token) > MAX_PREFILL_TOKEN_LENGTH:
        raise AppError(422, "forms.prefill_too_long")
    # the values may name people: only which keys were set is logged
    audit.record(
        db, "form.prefill_link_created", entity=form,
        data={
            "hidden_keys": sorted(payload.hidden),
            "answers": len(payload.answers),
            "expires_at": expires_at.isoformat() if expires_at else None,
        },
    )
    db.commit()
    return PrefillLinkRead(token=token, expires_at=expires_at)
