from dataclasses import dataclass, field as dataclass_field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from common.services.text_scoring.scorer import score_text
from modules.audit import service as audit
from modules.auth.dto import EmployeePrincipal, Principal
from modules.events import service as events
from modules.forms import access as form_access
from modules.forms import repository as forms_repository
from modules.forms.model import Form, FormField
from modules.forms.service import as_answered, branch_key, ordered_sections, published
from modules.results import service as results_service

from . import repository
from .answer_rules import validate_answer_values
from .dto import (
    SubmissionDetail,
    SubmissionDetailField,
    SubmissionRead,
)
from .model import Submission


GRACE = timedelta(seconds=30)
AUTO_GRADABLE = {"single_choice", "multi_choice", "boolean", "text"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _has_gradable(form: Form) -> bool:
    return any(f.type in AUTO_GRADABLE for f in form.fields)


def emit_submission_event(
    db: Session, event_type: str, submission: Submission, *, organisation_id: Optional[int]
) -> None:
    """Adds the event to the caller's transaction (no commit). The submission
    must have its id (flush first when it's new)."""
    events.emit(
        db,
        event_type,
        aggregate_type="submission",
        aggregate_id=submission.id,
        organisation_id=organisation_id,
        payload={
            "submission_id": submission.id,
            "form_id": submission.form_id,
            "user_id": submission.user_id,
            "customer_id": submission.customer_id,
            "attempt_number": submission.attempt_number,
            "status": submission.status,
            "score": submission.score,
        },
    )


def emit_finalized_events(db: Session, submission: Submission, form: Form) -> None:
    """submitted or late, plus graded when the form has auto-graded questions."""
    emit_submission_event(db, f"submission.{submission.status}", submission,
                          organisation_id=form.organisation_id)
    if _has_gradable(form):
        emit_submission_event(db, "submission.graded", submission,
                              organisation_id=form.organisation_id)


def resolve_file_answers(
    db: Session, form: Form, answers: dict[str, Any], *, actor, submission_id: Optional[int]
) -> tuple[dict[str, Any], list]:
    """Checks every file answer against the file service and swaps it for
    the stored form {file_id, name, content_type, size}. Returns the answers
    and the files they use (attach them once the submission has an id)."""
    from modules.files import service as files

    out = dict(answers)
    used = []
    file_answers = [
        (field, out.get(str(field.id)))
        for field in form.fields
        if field.type == "file" and isinstance(out.get(str(field.id)), dict)
    ]
    preloaded = files.load_answer_files(db, [value for _, value in file_answers])
    for field, value in file_answers:
        file, stored = files.resolve_answer_file(
            db, form_id=form.id, organisation_id=form.organisation_id, field_id=field.id,
            value=value, actor=actor, submission_id=submission_id, preloaded=preloaded,
        )
        out[str(field.id)] = stored
        used.append(file)
    return out, used


def attach_answer_files(db: Session, submission: Submission, used: list, form: Form) -> None:
    """Attaches the files the answers use; files this submission no longer
    uses (replaced or removed answers) are deleted. No commit."""
    from modules.files import repository as files_repository
    from modules.files import service as files

    if not used and not any(f.type == "file" for f in form.fields):
        return
    keep = {f.id for f in used}
    for file in used:
        files.attach(db, file, attached_type="submission", attached_id=submission.id)
    for file in files_repository.attached_files(db, "submission", [submission.id]):
        if file.id not in keep:
            files.discard(db, file)


def _normalize_multi(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, str):
        return {part.strip() for part in value.split(",") if part.strip()}
    if isinstance(value, (list, tuple, set)):
        return {str(v).strip() for v in value if str(v).strip()}
    return {str(value).strip()}


def _correctness_fraction(field: FormField, answer: Any) -> float:
    if field.right_answer is None:
        return 0.0
    if field.type == "multi_choice":
        return 1.0 if _normalize_multi(answer) == _normalize_multi(field.right_answer) else 0.0
    if field.type == "boolean":
        return 1.0 if str(answer).strip().lower() == field.right_answer.strip().lower() else 0.0
    if field.type == "single_choice":
        return 1.0 if str(answer).strip() == field.right_answer.strip() else 0.0
    if field.type == "text":
        if answer is None or not str(answer).strip():
            return 0.0
        return score_text(str(answer), field.right_answer)
    return 0.0


def _required_missing(field: FormField, answers: dict[str, Any]) -> bool:
    if not field.is_required:
        return False
    provided = answers.get(str(field.id))
    if provided is None:
        return True
    if isinstance(provided, str) and provided == "":
        return True
    if isinstance(provided, (list, tuple, set)) and len(provided) == 0:
        return True
    return False


def _visited_section_ids(form: Form, answers: dict[str, Any]) -> Optional[set[int]]:
    """Walk the sections following branching rules. None means the form has no
    sections, so every field is on the path."""
    if not form.sections:
        return None
    ordered = ordered_sections(form.sections)
    position = {s["id"]: i for i, s in enumerate(ordered)}
    # a section's first branching question (by order, then id) holds its
    # rules; the form fillers pick the same one
    rules_by_section: dict[int, tuple[FormField, dict[str, Any]]] = {}
    for f in sorted(form.fields, key=lambda f: (f.order, f.id)):
        if f.branching and f.section_id is not None:
            rules_by_section.setdefault(
                f.section_id,
                (f, {branch_key(f.type, k): t for k, t in f.branching.items()}),
            )

    visited: set[int] = set()
    i = 0
    # every step either ends the walk or moves strictly forward
    while i < len(ordered):
        section = ordered[i]
        visited.add(section["id"])

        target = None
        rule = rules_by_section.get(section["id"])
        if rule is not None:
            field, branching = rule
            answer = answers.get(str(field.id))
            if answer is not None:
                target = branching.get(branch_key(field.type, answer))
        if target is None:
            target = section.get("next_section_id")

        if target == "end":
            break
        if target in position and position[target] > i:
            i = position[target]
        else:
            i += 1
    return visited


def _skipped_field_ids(form: Form, visited: Optional[set[int]]) -> set[str]:
    """Answer keys of fields on sections the path skipped. Fields not tied to a
    known section are never skipped."""
    if visited is None:
        return set()
    known = {s["id"] for s in form.sections or []}
    return {
        str(f.id)
        for f in form.fields
        if f.section_id in known and f.section_id not in visited
    }


def _prune_to_path(
    form: Form, answers: dict[str, Any], visited: Optional[set[int]]
) -> dict[str, Any]:
    """Keep only answers to the form's current fields on sections the
    respondent's path went through. A draft can outlive a structural edit, so
    answers to removed fields are dropped too."""
    keep = {str(f.id) for f in form.fields} - _skipped_field_ids(form, visited)
    return {k: v for k, v in answers.items() if k in keep}


def _validate_required(
    form: Form, answers: dict[str, Any], visited: Optional[set[int]] = None
) -> None:
    skipped = _skipped_field_ids(form, visited)
    for field in form.fields:
        if str(field.id) in skipped:
            continue
        if _required_missing(field, answers):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"Field {field.id} ({field.question}) is required",
            )


@dataclass
class Grade:
    """A submission's score and how it was reached (E1.6)."""
    total: float  # 0–100
    # sections on the path that have graded questions: {"id", "score" 0–100, "weight"}
    sections: list[dict[str, Any]] = dataclass_field(default_factory=list)
    # graded questions that count (weight above 0, on the path): field id -> (earned, possible)
    questions: dict[int, tuple[float, float]] = dataclass_field(default_factory=dict)

    def as_json(self, form: Form) -> dict[str, Any]:
        keys = {f.id: f.key for f in form.fields}
        return {
            "total": self.total,
            "sections": self.sections,
            "questions": [
                {"field_id": fid, "key": keys.get(fid), "score": earned, "max": possible}
                for fid, (earned, possible) in self.questions.items()
            ],
        }


def _earned(field: FormField, answers: dict[str, Any], questions: dict) -> float:
    # questions worth nothing aren't graded: they can't change the score,
    # and grading a text answer runs the similarity model
    if not field.score_weight:
        return 0.0
    earned = field.score_weight * _correctness_fraction(field, answers.get(str(field.id)))
    questions[field.id] = (earned, field.score_weight)
    return earned


def grade(
    form: Form, answers: dict[str, Any], visited: Optional[set[int]] = None
) -> Grade:
    questions: dict[int, tuple[float, float]] = {}
    if not form.sections:
        total_possible = sum(f.score_weight for f in form.fields if f.type in AUTO_GRADABLE)
        if not total_possible:
            return Grade(total=0.0)
        earned = sum(
            _earned(f, answers, questions) for f in form.fields if f.type in AUTO_GRADABLE
        )
        return Grade(total=(earned / total_possible) * 100, questions=questions)

    # Section-weighted scoring — returns 0–100, over the sections on the path
    gradable_by_section: dict[int, list[FormField]] = {}
    for f in form.fields:
        if f.type in AUTO_GRADABLE:
            gradable_by_section.setdefault(f.section_id, []).append(f)
    # only sections with something to grade share the weight, so a section
    # without graded questions can't cap the score below 100
    sections = [
        s
        for s in form.sections
        if (visited is None or s["id"] in visited)
        and sum(f.score_weight for f in gradable_by_section.get(s["id"], [])) > 0
    ]
    total_sw = sum(s.get("score_weight", 1.0) for s in sections)
    if not total_sw:
        return Grade(total=0.0)
    score = 0.0
    breakdown: list[dict[str, Any]] = []
    for section in sections:
        fields = gradable_by_section[section["id"]]
        total_fw = sum(f.score_weight for f in fields)
        earned = sum(_earned(f, answers, questions) for f in fields)
        weight = section.get("score_weight", 1.0)
        score += (weight / total_sw) * (earned / total_fw) * 100
        breakdown.append({"id": section["id"], "score": (earned / total_fw) * 100, "weight": weight})
    return Grade(total=score, sections=breakdown, questions=questions)


def _score(
    form: Form, answers: dict[str, Any], visited: Optional[set[int]] = None
) -> float:
    return grade(form, answers, visited).total


def _unit_of(principal: Optional[Principal]) -> Optional[int]:
    """The unit a signed-in employee's answers count under (see SubmissionValue)."""
    return principal.unit_id if isinstance(principal, EmployeePrincipal) else None


def record_results(
    db: Session, submission: Submission, form: Form, result: Grade, *, unit_id: Optional[int]
) -> None:
    """Score, breakdown and one row per answer for a submission just
    finalized. The submission needs its id. No commit."""
    submission.score = result.total
    submission.scores = result.as_json(form)
    results_service.add_values(db, submission, form, result.questions, unit_id=unit_id)


def regrade_submission(db: Session, submission: Submission, *, update_score: bool) -> str:
    """Grades a finished submission again from its stored answers, against
    the version it answered, and rewrites its answer rows. No commit.

    With update_score=False the stored score is kept: when the grade comes
    out different (older submissions were scored by older rules) the
    breakdown is left unset rather than contradict the score. Returns
    "same", "changed" (score updated) or "differs" (kept)."""
    form = as_answered(submission)
    answers = submission.answers or {}
    result = grade(form, answers, _visited_section_ids(form, answers))
    unit_id = submission.employee.unit_id if submission.employee is not None else None
    results_service.replace_values(db, submission, form, result.questions, unit_id=unit_id)
    same = submission.score is not None and abs(submission.score - result.total) < 1e-9
    if not same and update_score:
        audit.record(
            db, "submission.score_changed", entity_type="submission", entity_id=submission.id,
            organisation_id=submission.form.organisation_id,
            changes={"score": [submission.score, result.total]},
            data={"form_id": submission.form_id, "version_id": submission.form_version_id},
        )
    if same or update_score:
        submission.score = result.total
        submission.scores = result.as_json(form)
        return "same" if same else "changed"
    submission.scores = None
    return "differs"


def rebuild_results(
    db: Session, *, form_id: Optional[int] = None, update_score: bool = False, batch_size: int = 200
) -> dict[str, int]:
    """Regrades every finished submission (of one form, or all), committing
    each batch. Safe to run again: each run rewrites the same rows."""
    counts = {"same": 0, "changed": 0, "differs": 0}
    after = 0
    while True:
        batch = repository.finalized_after(db, after_id=after, form_id=form_id, limit=batch_size)
        if not batch:
            return counts
        for submission in batch:
            counts[regrade_submission(db, submission, update_score=update_score)] += 1
        after = batch[-1].id
        db.commit()


def _ensure_submitter_allowed(form: Form, principal_type: str) -> None:
    if not form.is_active:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Form is not accepting submissions"
        )
    if form.is_archived:
        raise HTTPException(status.HTTP_409_CONFLICT, "Form is archived")
    if principal_type not in (form.submitter_type or []):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"{principal_type}s are not allowed to submit this form",
        )


def _ensure_user_can_access_form(form: Form, principal: Principal) -> None:
    """Unit-targeting check. Customers have no unit; if the form is unit-targeted,
    customers see only forms with empty/null assigned_to_units."""
    if isinstance(principal, EmployeePrincipal):
        if form.organisation_id != principal.organisation_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Form not found")
        assigned = form.assigned_to_units or []
        if not assigned:
            return
        unit_ids = set(principal.assigned_unit_ids or [])
        if principal.unit_id is not None:
            unit_ids.add(principal.unit_id)
        if not (unit_ids & set(assigned)):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "Form is not assigned to your unit"
            )
    else:
        # customer: no unit gating, only submitter_type gates them
        if form.assigned_to_units:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "Form is not assigned to you"
            )


def _principal_ids(principal: Principal) -> tuple[Optional[int], Optional[int]]:
    """Return (user_id, customer_id) tuple for the principal."""
    if principal.principal == "employee":
        return principal.id, None
    return None, principal.id


def _ensure_owner(submission: Submission, principal: Principal) -> None:
    user_id, customer_id = _principal_ids(principal)
    if user_id is not None and submission.user_id == user_id:
        return
    if customer_id is not None and submission.customer_id == customer_id:
        return
    raise HTTPException(
        status.HTTP_403_FORBIDDEN, "You can only access your own submissions"
    )


def _ensure_can_view(submission: Submission, principal: Principal) -> None:
    if isinstance(principal, EmployeePrincipal):
        # owners always can
        if submission.user_id == principal.id:
            return
        # same org + reviewer of the form
        if submission.form is not None and submission.form.organisation_id == principal.organisation_id:
            if form_access.can_review(principal, submission.form):
                return
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Not allowed to view this submission"
        )
    _ensure_owner(submission, principal)


def _ensure_in_progress(submission: Submission) -> None:
    if submission.status != "in_progress":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Submission is {submission.status}; cannot be modified",
        )


def _check_and_apply_expiry(
    db: Session, submission: Submission
) -> bool:
    """If session is in_progress past expiry+grace, flip to expired & commit.
    Returns True if expired was applied."""
    if submission.status != "in_progress" or submission.expires_at is None:
        return False
    if _now() > submission.expires_at + GRACE:
        submission.status = "expired"
        emit_submission_event(db, "submission.expired", submission,
                              organisation_id=submission.form.organisation_id if submission.form else None)
        repository.save(db, submission)
        return True
    return False


def expire_abandoned_attempts(db: Session) -> int:
    """Background sweep: expires timed attempts the respondent walked away
    from, using the same grace period as the on-request check."""
    expired = repository.expire_open_submissions_before(db, _now() - GRACE)
    for submission, organisation_id in expired:
        emit_submission_event(db, "submission.expired", submission, organisation_id=organisation_id)
    db.commit()
    return len(expired)


def get_respondent_form(
    db: Session, *, submission_id: int, principal: Principal
) -> Form:
    """The form behind the caller's own in-progress submission. Tying the
    questions to a started attempt means they can't be read before the timer
    runs, and the respondent view never carries the correct answers."""
    submission = repository.get_submission(db, submission_id)
    if submission is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Submission not found")
    _ensure_owner(submission, principal)
    if _check_and_apply_expiry(db, submission):
        raise HTTPException(status.HTTP_409_CONFLICT, "Submission has expired")
    _ensure_in_progress(submission)
    return as_answered(submission)


def _ensure_attempt_quota(
    db: Session, form: Form, principal: Principal
) -> int:
    """Return the attempt_number for the *new* attempt; raise if over quota."""
    user_id, customer_id = _principal_ids(principal)
    used = repository.count_finalized_attempts(
        db, form_id=form.id, user_id=user_id, customer_id=customer_id
    )
    if form.max_attempts is not None and used >= form.max_attempts:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"You have used all {form.max_attempts} attempt(s) for this form",
        )
    return used + 1


def start_submission(
    db: Session, *, form_id: int, principal: Principal
) -> Submission:
    form = forms_repository.get_form(db, form_id)
    if form is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Form not found")

    _ensure_submitter_allowed(form, principal.principal)
    _ensure_user_can_access_form(form, principal)
    if published(form) is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Form has not been published yet")

    user_id, customer_id = _principal_ids(principal)

    open_sub = repository.find_open_submission(
        db, form_id=form.id, user_id=user_id, customer_id=customer_id
    )
    if open_sub is not None:
        # if it has gone past expiry+grace, expire it and proceed to a fresh attempt
        if _check_and_apply_expiry(db, open_sub):
            open_sub = None
        else:
            # an attempt started before a publish carries on with its version
            return open_sub

    attempt_number = _ensure_attempt_quota(db, form, principal)

    expires_at: Optional[datetime] = None
    if form.type == "exam" and form.time_limit_minutes:
        expires_at = _now() + timedelta(minutes=form.time_limit_minutes)

    return repository.create_submission(
        db,
        form_id=form.id,
        user_id=user_id,
        customer_id=customer_id,
        expires_at=expires_at,
        attempt_number=attempt_number,
        form_version_id=form.current_version_id,
    )


def save_draft(
    db: Session,
    *,
    submission_id: int,
    answers: dict[str, Any],
    principal: Principal,
) -> Submission:
    submission = repository.get_submission(db, submission_id)
    if submission is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Submission not found")
    _ensure_owner(submission, principal)
    if _check_and_apply_expiry(db, submission):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Submission has expired; draft cannot be saved"
        )
    _ensure_in_progress(submission)
    # merge answers (partial allowed); only the version's own questions are
    # kept, with values bounded by type and size
    form = as_answered(submission)
    known = {str(f.id) for f in form.fields}
    incoming = {k: v for k, v in (answers or {}).items() if k in known}
    validate_answer_values(form, incoming, draft=True)
    merged = dict(submission.answers or {})
    merged.update(incoming)
    merged, used = resolve_file_answers(db, form, merged, actor=principal, submission_id=submission.id)
    attach_answer_files(db, submission, used, form)
    submission.answers = merged
    return repository.save(db, submission)


def submit_submission(
    db: Session,
    *,
    submission_id: int,
    answers: Optional[dict[str, Any]],
    principal: Principal,
) -> Submission:
    submission = repository.get_submission(db, submission_id)
    if submission is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Submission not found")
    _ensure_owner(submission, principal)
    if _check_and_apply_expiry(db, submission):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Submission has expired"
        )
    _ensure_in_progress(submission)

    if answers:
        merged = dict(submission.answers or {})
        merged.update(answers)
        submission.answers = merged

    form = as_answered(submission)
    answers = submission.answers or {}
    visited = _visited_section_ids(form, answers)
    final_answers = _prune_to_path(form, answers, visited)
    submission.answers = final_answers
    validate_answer_values(form, final_answers)
    _validate_required(form, final_answers, visited)
    # files on skipped branches were pruned above, so they are released here
    final_answers, used = resolve_file_answers(db, form, final_answers, actor=principal, submission_id=submission.id)
    attach_answer_files(db, submission, used, form)
    submission.answers = final_answers

    now = _now()
    is_late = bool(submission.expires_at and now > submission.expires_at)
    submission.status = "late" if is_late else "submitted"
    submission.submitted_at = now
    record_results(db, submission, form, grade(form, final_answers, visited),
                   unit_id=_unit_of(principal))
    emit_finalized_events(db, submission, form)
    return repository.save(db, submission)


def get_submission(
    db: Session, *, submission_id: int, principal: Principal
) -> Submission:
    submission = repository.get_submission(db, submission_id)
    if submission is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Submission not found")
    _check_and_apply_expiry(db, submission)
    _ensure_can_view(submission, principal)
    return submission


def list_submissions(
    db: Session,
    *,
    principal: Principal,
    form_id: Optional[int],
    mine_only: bool,
    status_in: Optional[list[str]],
    submitter_search: Optional[str],
    sort_by: str,
    sort_dir: str,
    limit: int,
    offset: int,
) -> tuple[list[Submission], int]:
    customer_id: Optional[int] = None
    user_id: Optional[int] = None
    organisation_id: Optional[int] = None

    if isinstance(principal, EmployeePrincipal):
        can_view_all = form_access.can_review_all(principal)
        organisation_id = principal.organisation_id
        if mine_only:
            user_id = principal.id
        elif not can_view_all:
            # form creators can see all submissions for their own form
            is_form_creator = False
            if form_id is not None:
                owned = forms_repository.get_form(db, form_id)
                is_form_creator = owned is not None and owned.created_by == principal.id
            if not is_form_creator:
                user_id = principal.id
    else:
        customer_id = principal.id

    items = repository.list_submissions(
        db,
        form_id=form_id,
        customer_id=customer_id,
        user_id=user_id,
        organisation_id=organisation_id,
        status_in=status_in,
        submitter_search=submitter_search,
        sort_by=sort_by,
        sort_dir=sort_dir,
        limit=limit,
        offset=offset,
    )
    total = repository.count_submissions(
        db,
        form_id=form_id,
        customer_id=customer_id,
        user_id=user_id,
        organisation_id=organisation_id,
        status_in=status_in,
        submitter_search=submitter_search,
    )
    return items, total


def _submitter_name(submission: Submission) -> Optional[str]:
    if submission.employee is not None:
        return submission.employee.username
    # public submissions: the name given this time, then the customer record
    contact = submission.contact or {}
    if contact.get("first_name") or contact.get("last_name"):
        return f"{contact.get('first_name', '')} {contact.get('last_name', '')}".strip()
    if submission.customer is not None:
        return f"{submission.customer.first_name} {submission.customer.last_name}"
    return None


def serialize_read(submission: Submission, *, principal: Principal) -> SubmissionRead:
    """Return a SubmissionRead with score nulled out when results are not yet revealed."""
    form = submission.form

    is_owner = (
        (principal.principal == "employee" and submission.user_id == principal.id)
        or (principal.principal == "customer" and submission.customer_id == principal.id)
    )

    is_reviewer = False
    if isinstance(principal, EmployeePrincipal) and form is not None:
        if form.organisation_id == principal.organisation_id:
            is_reviewer = form_access.can_review(principal, form)

    revealed = bool(
        is_reviewer
        or (is_owner and (submission.results_revealed or (form and form.results_revealed)))
    )

    read = SubmissionRead.model_validate(submission)
    read.submitter_name = _submitter_name(submission)
    if not revealed:
        read.score = None
    return read


def reveal_submission(
    db: Session, *, submission_id: int, principal: Principal
) -> Submission:
    if not isinstance(principal, EmployeePrincipal):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only reviewers can reveal results")
    submission = repository.get_submission(db, submission_id)
    if submission is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Submission not found")
    form = submission.form
    if form is None or form.organisation_id != principal.organisation_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Submission not found")
    if not form_access.can_review(principal, form):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed to reveal this submission")
    submission.results_revealed = True
    return repository.save(db, submission)


def serialize_detail(
    submission: Submission, *, principal: Principal
) -> SubmissionDetail:
    """Serialize a submission for the detail endpoint, reveal-gating sensitive bits.
    Questions come from the version answered, not the form as it is now."""
    form = as_answered(submission) if submission.form is not None else None

    is_owner = False
    if principal.principal == "employee" and submission.user_id == principal.id:
        is_owner = True
    elif principal.principal == "customer" and submission.customer_id == principal.id:
        is_owner = True

    is_reviewer = False
    if isinstance(principal, EmployeePrincipal) and form is not None:
        if form.organisation_id == principal.organisation_id:
            is_reviewer = form_access.can_review(principal, form)

    revealed = bool(
        is_reviewer
        or (is_owner and (submission.results_revealed or (form and form.results_revealed)))
    )

    # A finalized submission's answers were pruned to its path, and the
    # branching answers sit on visited sections, so the walk recovers the path.
    # Drafts are left alone: their respondent may still reach later sections.
    skipped: set[str] = set()
    if form is not None and submission.status in ("submitted", "late"):
        visited = _visited_section_ids(form, submission.answers or {})
        skipped = _skipped_field_ids(form, visited)

    fields: list[SubmissionDetailField] = []
    if form is not None:
        for f in form.fields:
            data = SubmissionDetailField(
                id=f.id,
                order=f.order,
                type=f.type,
                is_required=f.is_required,
                score_weight=f.score_weight,
                skipped=str(f.id) in skipped,
            )
            if revealed:
                data.question = f.question
                data.options = f.options
                data.right_answer = f.right_answer
                data.help_text = f.help_text
            fields.append(data)

    answers = submission.answers if (is_owner or is_reviewer) and revealed else None

    base = SubmissionRead.model_validate(submission)
    base.submitter_name = _submitter_name(submission)
    if not revealed:
        base.score = None
    return SubmissionDetail(
        **base.model_dump(),
        # personal details: for the form's reviewers only
        contact=submission.contact if is_reviewer else None,
        answers=answers,
        scores=submission.scores if revealed else None,
        fields=fields,
    )


def delete_submission(
    db: Session, *, submission_id: int, principal: Principal
) -> None:
    submission = repository.get_submission(db, submission_id)
    if submission is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Submission not found")
    _ensure_owner(submission, principal)
    if submission.status != "in_progress":
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Finalized submissions cannot be deleted"
        )
    from modules.files import service as files

    files.delete_attached(db, attached_type="submission", attached_ids=[submission.id])
    repository.delete_submission(db, submission)
