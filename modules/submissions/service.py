import hmac
from dataclasses import dataclass, field as dataclass_field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session

from common.errors import AppError
from common.services.text_scoring.scorer import score_text
from modules.audit import service as audit
from modules.auth.dto import EmployeePrincipal, Principal
from modules.events import service as events
from modules.forms import access as form_access
from modules.forms import behaviour
from modules.forms import repository as forms_repository
from modules.forms.dto import DISPLAY_TYPES, EndingScreen, respondent_config
from modules.forms.model import Form, FormField
from modules.forms import logic
from modules.forms.logic import Path
from modules.forms.service import as_answered, published
from modules.results import service as results_service

from . import repository
from .answer_rules import is_incomplete, validate_answer_values
from .dto import (
    SubmissionDetail,
    SubmissionDetailField,
    SubmissionRead,
)
from .model import Submission


GRACE = timedelta(seconds=30)
# the scoring hook: types _correctness_fraction can mark. Scale, rating,
# NPS and Likert points are E2.4 (T2.4.2).
AUTO_GRADABLE = {"single_choice", "multi_choice", "boolean", "text", "dropdown"}


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


def resolve_keeping_stored(
    db: Session, form: Form, answers: dict[str, Any], *, stored: Optional[dict[str, Any]], actor,
    submission_id: int,
) -> tuple[dict[str, Any], list]:
    """resolve_file_answers for a submission that already has answers: a file
    answer sent back as stored (same file, no upload token) is kept as it is.
    A public respondent can't prove a stored file is theirs again, since its
    token was only handed out at upload."""
    from modules.files import repository as files_repository

    stored = stored or {}
    kept = {
        k for k, v in answers.items()
        if isinstance(v, dict) and "token" not in v and isinstance(stored.get(k), dict)
        and stored[k].get("file_id") == v.get("file_id")
    }
    out, used = resolve_file_answers(
        db, form, {k: v for k, v in answers.items() if k not in kept}, actor=actor, submission_id=submission_id,
    )
    if kept:
        attached = {f.id: f for f in files_repository.attached_files(db, "submission", [submission_id])}
        for k in kept:
            file = attached.get(stored[k]["file_id"])
            if file is None:
                raise AppError(422, "submissions.answer_invalid", question=k, problem="names a file that is gone")
            out[k] = stored[k]
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
    if field.type in ("single_choice", "dropdown"):
        return 1.0 if str(answer).strip() == field.right_answer.strip() else 0.0
    if field.type == "text":
        if answer is None or not str(answer).strip():
            return 0.0
        return score_text(str(answer), field.right_answer)
    return 0.0


def _required_missing(field: FormField, answers: dict[str, Any]) -> bool:
    if not field.is_required or field.type in DISPLAY_TYPES:
        return False
    return is_incomplete(field, answers.get(str(field.id)))


def path_of(form: Form, answers: Optional[dict[str, Any]], hidden: Optional[dict[str, Any]] = None) -> Path:
    """Where these answers lead (E2.3): the sections visited and the
    questions shown. The browser works out the same path (utils/form/logic.ts)."""
    return logic.walk(form, answers or {}, hidden)


def _prune_to_path(
    form: Form, answers: dict[str, Any], path: Optional[Path]
) -> dict[str, Any]:
    """Keep only answers to the form's current questions that the
    respondent's path showed. A draft can outlive a structural edit, so
    answers to removed fields are dropped too."""
    keep = _answerable_ids(form) - logic.not_shown_ids(form, path)
    return {k: v for k, v in answers.items() if k in keep}


def _answerable_ids(form: Form) -> set[str]:
    """Answer keys of the questions; display blocks take no answer."""
    return {str(f.id) for f in form.fields if f.type not in DISPLAY_TYPES}


def _validate_required(
    form: Form, answers: dict[str, Any], path: Optional[Path] = None
) -> None:
    """Required questions the path showed must be answered; skipped and
    hidden ones needn't be."""
    not_shown = logic.not_shown_ids(form, path)
    for field in form.fields:
        if str(field.id) in not_shown:
            continue
        if _required_missing(field, answers):
            raise AppError(422, "submissions.field_required", id=field.id, question=field.question)


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
    form: Form, answers: dict[str, Any], visited: Optional[set[int]] = None,
    shown: Optional[set[int]] = None,
) -> Grade:
    """The score over the sections `visited` and the questions `shown`
    (None: all). A hidden question counts as a skipped one (E2.3); other
    rules for them are T2.4.5."""
    questions: dict[int, tuple[float, float]] = {}
    gradable = [
        f for f in form.fields if f.type in AUTO_GRADABLE and (shown is None or f.id in shown)
    ]
    if not form.sections:
        total_possible = sum(f.score_weight for f in gradable)
        if not total_possible:
            return Grade(total=0.0)
        earned = sum(_earned(f, answers, questions) for f in gradable)
        return Grade(total=(earned / total_possible) * 100, questions=questions)

    # Section-weighted scoring — returns 0–100, over the sections on the path
    gradable_by_section: dict[int, list[FormField]] = {}
    for f in gradable:
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


def grade_path(form: Form, answers: dict[str, Any], path: Path) -> Grade:
    return grade(form, answers, path.visited, path.shown)


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
    result = grade_path(form, answers, path_of(form, answers, submission.hidden_fields))
    results_service.replace_values(db, submission, form, result.questions, unit_id=counted_unit(db, submission))
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


def counted_unit(db: Session, submission: Submission) -> Optional[int]:
    """The unit a finished submission's answers count under: the respondent's
    unit, or (anonymous and public ones) the unit its rows already have."""
    if submission.employee is not None:
        return submission.employee.unit_id
    return results_service.unit_of(db, submission.id)


def _ensure_submitter_allowed(form: Form, principal_type: str) -> None:
    if not form.is_active:
        raise AppError(409, "public_forms.closed")
    if form.is_archived:
        raise AppError(409, "submissions.form_archived")
    if principal_type not in (form.submitter_type or []):
        raise AppError(403, "submissions.submitter_not_allowed", principal_type=principal_type)


def _ensure_user_can_access_form(form: Form, principal: Principal) -> None:
    """Unit-targeting check. Customers have no unit; if the form is unit-targeted,
    customers see only forms with empty/null assigned_to_units."""
    if isinstance(principal, EmployeePrincipal):
        if form.organisation_id != principal.organisation_id:
            raise AppError(404, "forms.not_found")
        assigned = form.assigned_to_units or []
        if not assigned:
            return
        unit_ids = set(principal.assigned_unit_ids or [])
        if principal.unit_id is not None:
            unit_ids.add(principal.unit_id)
        if not (unit_ids & set(assigned)):
            raise AppError(403, "submissions.not_your_unit")
    else:
        # customer: no unit gating, only submitter_type gates them
        if form.assigned_to_units:
            raise AppError(403, "submissions.not_assigned")


def _principal_ids(principal: Principal) -> tuple[Optional[int], Optional[int]]:
    """Return (user_id, customer_id) tuple for the principal."""
    if principal.principal == "employee":
        return principal.id, None
    return None, principal.id


def _load(db: Session, submission_id: int, principal: Principal) -> Submission:
    """The submission, or 404 when it doesn't exist or belongs to another
    organisation's form, checked before anything else so the answer never
    shows whether it exists there."""
    submission = repository.get_submission(db, submission_id)
    if submission is None:
        raise AppError(404, "submissions.not_found")
    if isinstance(principal, EmployeePrincipal):
        form = submission.form
        if form is None or form.organisation_id != principal.organisation_id:
            raise AppError(404, "submissions.not_found")
    return submission


def _anonymous_key(form_id: int, principal: Principal) -> str:
    return behaviour.respondent_key(form_id, principal.principal, principal.id)


def is_owner(submission: Submission, principal: Principal) -> bool:
    """The caller answered it: by id, or on an anonymous form (no id stored)
    by the keyed stand-in only they produce."""
    user_id, customer_id = _principal_ids(principal)
    if user_id is not None and submission.user_id == user_id:
        return True
    if customer_id is not None and submission.customer_id == customer_id:
        return True
    if submission.user_id is None and submission.customer_id is None and submission.respondent_key:
        return hmac.compare_digest(submission.respondent_key, _anonymous_key(submission.form_id, principal))
    return False


def _ensure_owner(submission: Submission, principal: Principal) -> None:
    if not is_owner(submission, principal):
        raise AppError(403, "submissions.own_only")


def _ensure_can_view(submission: Submission, principal: Principal) -> None:
    if isinstance(principal, EmployeePrincipal):
        # owners always can
        if is_owner(submission, principal):
            return
        # same org + reviewer of the form
        if submission.form is not None and submission.form.organisation_id == principal.organisation_id:
            if form_access.can_review(principal, submission.form):
                return
        raise AppError(403, "submissions.view_denied")
    _ensure_owner(submission, principal)


def _ensure_in_progress(submission: Submission) -> None:
    if submission.status != "in_progress":
        raise AppError(409, "submissions.locked", status=submission.status)


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
) -> tuple[Form, Submission]:
    """The form behind the caller's own in-progress submission (or a
    submitted one they may still change). Tying the questions to a started
    attempt means they can't be read before the timer runs, and the
    respondent view never carries the correct answers."""
    submission = _load(db, submission_id, principal)
    _ensure_owner(submission, principal)
    if _check_and_apply_expiry(db, submission):
        raise AppError(409, "submissions.expired")
    if not behaviour.can_edit(submission.form, submission):
        _ensure_in_progress(submission)
    return as_answered(submission), submission


def _ensure_attempt_quota(
    db: Session, form: Form, principal: Principal, *, respondent_key: Optional[str] = None
) -> int:
    """Return the attempt_number for the *new* attempt; raise if over quota.
    One response per person (T2.2.4) caps it at 1."""
    user_id, customer_id = (None, None) if respondent_key else _principal_ids(principal)
    used = repository.count_finalized_attempts(
        db, form_id=form.id, user_id=user_id, customer_id=customer_id, respondent_key=respondent_key,
    )
    raise_if_over_quota(form, used, prefix="submissions")
    return used + 1


def raise_if_over_quota(form, used: int, *, prefix: str) -> None:
    limit = behaviour.max_attempts(form)
    if limit is None or used < limit:
        return
    if behaviour.settings_of(form).one_response_per_person:
        raise AppError(409, f"{prefix}.already_responded")
    raise AppError(409, f"{prefix}.max_attempts" if prefix == "public_forms" else "submissions.attempts_used",
                   max_attempts=limit)


def prefilled(form, view, token: Optional[str], *, code: str) -> Optional[behaviour.Prefill]:
    """A prefilled link's values, with its answers checked against the
    version being answered (a link made for an older version keeps only
    what still fits)."""
    prefill = behaviour.read_prefill(form, token, code=code)
    if prefill is None:
        return None
    known = _answerable_ids(view)
    file_ids = {str(f.id) for f in view.fields if f.type == "file"}
    answers = {k: v for k, v in prefill.answers.items() if k in known and k not in file_ids}
    try:
        validate_answer_values(view, answers, draft=True)
    except AppError:
        answers = {}
    prefill.answers = answers
    return prefill


def start_submission(
    db: Session, *, form_id: int, principal: Principal, prefill: Optional[str] = None
) -> Submission:
    form = forms_repository.get_form(db, form_id)
    if form is None:
        raise AppError(404, "forms.not_found")

    # another organisation's form is missing, whatever state it is in
    if isinstance(principal, EmployeePrincipal) and form.organisation_id != principal.organisation_id:
        raise AppError(404, "forms.not_found")
    _ensure_submitter_allowed(form, principal.principal)
    _ensure_user_can_access_form(form, principal)
    view = published(form)
    if view is None:
        raise AppError(409, "submissions.form_unpublished")
    behaviour.ensure_taking_responses(form, prefix="submissions")

    # an anonymous form stores no id, only the keyed stand-in (T2.2.8)
    key = _anonymous_key(form.id, principal) if behaviour.is_anonymous(form) else None
    user_id, customer_id = (None, None) if key else _principal_ids(principal)

    open_sub = repository.find_open_submission(
        db, form_id=form.id, user_id=user_id, customer_id=customer_id, respondent_key=key,
    )
    if open_sub is not None:
        # if it has gone past expiry+grace, expire it and proceed to a fresh attempt
        if _check_and_apply_expiry(db, open_sub):
            open_sub = None
        else:
            # an attempt started before a publish carries on with its version
            return open_sub

    attempt_number = _ensure_attempt_quota(db, form, principal, respondent_key=key)
    filled = prefilled(form, view, prefill, code="submissions.prefill_invalid")

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
        respondent_key=key,
        hidden_fields=(filled.hidden or None) if filled else None,
        answers=filled.answers if filled else None,
        # the order this attempt is shown, kept for the attempt (T2.2.9)
        question_order=behaviour.shuffled_order(view, behaviour.new_seed()),
    )


def save_draft(
    db: Session,
    *,
    submission_id: int,
    answers: dict[str, Any],
    principal: Principal,
) -> Submission:
    submission = _load(db, submission_id, principal)
    _ensure_owner(submission, principal)
    if _check_and_apply_expiry(db, submission):
        raise AppError(409, "submissions.draft_expired")
    _ensure_in_progress(submission)
    # merge answers (partial allowed); only the version's own questions are
    # kept, with values bounded by type and size
    form = as_answered(submission)
    known = _answerable_ids(form)
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
    submission = _load(db, submission_id, principal)
    _ensure_owner(submission, principal)
    if _check_and_apply_expiry(db, submission):
        raise AppError(409, "submissions.expired")
    _ensure_in_progress(submission)
    # an attempt still open when the form closed can't be handed in after it
    behaviour.ensure_taking_responses(submission.form, prefix="submissions", grace=GRACE)

    if answers:
        merged = dict(submission.answers or {})
        merged.update(answers)
        submission.answers = merged

    form = as_answered(submission)
    answers = submission.answers or {}
    path = path_of(form, answers, submission.hidden_fields)
    final_answers = _prune_to_path(form, answers, path)
    submission.answers = final_answers
    validate_answer_values(form, final_answers)
    _validate_required(form, final_answers, path)
    # files on skipped branches and hidden questions were pruned above, so
    # they are released here
    final_answers, used = resolve_file_answers(db, form, final_answers, actor=principal, submission_id=submission.id)
    attach_answer_files(db, submission, used, form)
    submission.answers = final_answers

    now = _now()
    is_late = bool(submission.expires_at and now > submission.expires_at)
    submission.status = "late" if is_late else "submitted"
    submission.submitted_at = now
    record_results(db, submission, form, grade_path(form, final_answers, path),
                   unit_id=_unit_of(principal))
    emit_finalized_events(db, submission, form)
    return repository.save(db, submission)


def get_submission(
    db: Session, *, submission_id: int, principal: Principal
) -> Submission:
    submission = _load(db, submission_id, principal)
    # allowed first: someone who can't see it mustn't change it either
    _ensure_can_view(submission, principal)
    _check_and_apply_expiry(db, submission)
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


def is_anonymous_row(submission: Submission) -> bool:
    """Answered on an anonymous form: nobody's id or contact details are stored."""
    return submission.user_id is None and submission.customer_id is None and submission.contact is None \
        and bool(submission.respondent_key)


def submitter_name(submission: Submission) -> Optional[str]:
    return _submitter_name(submission)


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

    owner = is_owner(submission, principal)

    is_reviewer = False
    if isinstance(principal, EmployeePrincipal) and form is not None:
        if form.organisation_id == principal.organisation_id:
            is_reviewer = form_access.can_review(principal, form)

    revealed = bool(
        is_reviewer
        or (owner and (submission.results_revealed or (form and form.results_revealed)))
    )

    read = SubmissionRead.model_validate(submission)
    read.submitter_name = _submitter_name(submission)
    read.anonymous = is_anonymous_row(submission)
    if not revealed:
        read.score = None
    if owner and form is not None:
        read.editable_until = behaviour.editable_until(form, submission)
    return read


def reveal_submission(
    db: Session, *, submission_id: int, principal: Principal
) -> Submission:
    if not isinstance(principal, EmployeePrincipal):
        raise AppError(403, "submissions.reviewers_only")
    submission = _load(db, submission_id, principal)
    form = submission.form
    if not form_access.can_review(principal, form):
        raise AppError(403, "submissions.reveal_denied")
    submission.results_revealed = True
    return repository.save(db, submission)


def serialize_detail(
    submission: Submission, *, principal: Principal
) -> SubmissionDetail:
    """Serialize a submission for the detail endpoint, reveal-gating sensitive bits.
    Questions come from the version answered, not the form as it is now."""
    form = as_answered(submission) if submission.form is not None else None

    owner = is_owner(submission, principal)

    is_reviewer = False
    if isinstance(principal, EmployeePrincipal) and form is not None:
        if form.organisation_id == principal.organisation_id:
            is_reviewer = form_access.can_review(principal, form)

    revealed = bool(
        is_reviewer
        or (owner and (submission.results_revealed or (form and form.results_revealed)))
    )
    # an owner who may still change a response sees what they answered
    editing = owner and form is not None and behaviour.editable_until(form, submission) is not None

    # A finalized submission's answers were pruned to its path, and rules
    # read only answers on it, so the walk recovers the path. Drafts are
    # left alone: their respondent may still reach later sections.
    skipped: set[str] = set()
    if form is not None and submission.status in ("submitted", "late"):
        path = path_of(form, submission.answers or {}, submission.hidden_fields)
        skipped = logic.not_shown_ids(form, path)

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
                data.config = respondent_config(f.type, f.config)
            fields.append(data)

    answers = submission.answers if ((owner or is_reviewer) and revealed) or editing else None

    base = SubmissionRead.model_validate(submission)
    base.submitter_name = _submitter_name(submission)
    base.anonymous = is_anonymous_row(submission)
    if not revealed:
        base.score = None
    if owner and form is not None:
        base.editable_until = behaviour.editable_until(form, submission)
    return SubmissionDetail(
        **base.model_dump(),
        # personal details: for the form's reviewers only
        contact=submission.contact if is_reviewer else None,
        hidden_fields=submission.hidden_fields if is_reviewer else None,
        answers=answers,
        scores=submission.scores if revealed else None,
        fields=fields,
    )


def delete_submission(
    db: Session, *, submission_id: int, principal: Principal
) -> None:
    submission = _load(db, submission_id, principal)
    _ensure_owner(submission, principal)
    if submission.status != "in_progress":
        raise AppError(409, "submissions.finalized_not_deletable")
    from modules.files import service as files

    files.delete_attached(db, attached_type="submission", attached_ids=[submission.id])
    repository.delete_submission(db, submission)


# --- after submitting (E2.2) ----------------------------------------------------


def ending_for(submission: Submission) -> Optional[EndingScreen]:
    """The ending screen a finished submission earned (T2.2.2), or None for
    the default thank-you."""
    if submission.status not in ("submitted", "late") or submission.form is None:
        return None
    form = as_answered(submission)
    path = path_of(form, submission.answers or {}, submission.hidden_fields)
    return behaviour.pick_ending(form, score=submission.score, last_section_id=path.last_section_id)


def apply_edit(db: Session, submission: Submission, answers: dict[str, Any], *, actor) -> None:
    """Replaces a submitted response's answers within the form's edit window
    (T2.2.11): checked, scored and stored as a submit would, against the
    version answered. Logged and evented. No commit."""
    form = as_answered(submission)
    if behaviour.editable_until(form, submission) is None:
        raise AppError(409, "submissions.not_editable")
    if not behaviour.can_edit(form, submission):
        raise AppError(409, "submissions.edit_window_over")
    behaviour.ensure_taking_responses(submission.form, prefix="submissions", grace=GRACE)

    path = path_of(form, answers or {}, submission.hidden_fields)
    final_answers = _prune_to_path(form, answers or {}, path)
    validate_answer_values(form, final_answers)
    _validate_required(form, final_answers, path)
    final_answers, used = resolve_keeping_stored(
        db, form, final_answers, stored=submission.answers, actor=actor, submission_id=submission.id,
    )
    attach_answer_files(db, submission, used, form)

    before = submission.score
    submission.answers = final_answers
    submission.edited_at = _now()
    result = grade_path(form, final_answers, path)
    submission.score = result.total
    submission.scores = result.as_json(form)
    results_service.replace_values(db, submission, form, result.questions, unit_id=counted_unit(db, submission))
    changed = before is None or abs(before - result.total) > 1e-9
    audit.record(
        db, "submission.edited", entity_type="submission", entity_id=submission.id,
        organisation_id=form.organisation_id,
        changes={"score": [before, result.total]} if changed else None,
        data={"form_id": submission.form_id, "version_id": submission.form_version_id},
    )
    emit_submission_event(db, "submission.edited", submission, organisation_id=form.organisation_id)


def edit_submission(
    db: Session, *, submission_id: int, answers: dict[str, Any], principal: Principal
) -> Submission:
    submission = _load(db, submission_id, principal)
    _ensure_owner(submission, principal)
    apply_edit(db, submission, answers, actor=principal)
    return repository.save(db, submission)
