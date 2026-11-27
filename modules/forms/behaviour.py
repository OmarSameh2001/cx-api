"""How a form's E2.2 settings change what respondents get: when it takes
responses, which ending shows, the shuffled order, who counts as the same
respondent, and the signed links (prefilled, resume, edit). Pure rules on a
form or its published view; the services call them."""

import random
import secrets
from dataclasses import dataclass, field as dataclass_field
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from loguru import logger
from pydantic import ValidationError

from common.errors import AppError
from common.services import signing
from config import FormsEnv

from .dto import CHOICE_TYPES, DISPLAY_TYPES, EndingScreen, FormSettingsRead


def _now() -> datetime:
    return datetime.now(timezone.utc)


def settings_of(form) -> FormSettingsRead:
    """The form's settings with their defaults. A stored value that no longer
    fits is logged and read as the defaults rather than break the form."""
    try:
        return FormSettingsRead.model_validate(getattr(form, "settings", None) or {})
    except ValidationError as exc:
        logger.warning("form {}: stored settings don't fit ({}); using defaults", getattr(form, "id", None), exc)
        return FormSettingsRead()


# --- taking responses (T2.2.1) ---------------------------------------------------

OPEN, NOT_YET_OPEN, CLOSED = "open", "not_yet_open", "closed"


def availability(form, now: Optional[datetime] = None, *, grace: timedelta = timedelta(0)) -> str:
    s = settings_of(form)
    now = now or _now()
    if s.opens_at is not None and now < s.opens_at:
        return NOT_YET_OPEN
    if s.closes_at is not None and now > s.closes_at + grace:
        return CLOSED
    return OPEN


def ensure_taking_responses(form, *, prefix: str, grace: timedelta = timedelta(0)) -> None:
    """Raises `<prefix>.not_open_yet` or `<prefix>.closed_on` (or the form's
    own closed message) outside the form's dates."""
    state = availability(form, grace=grace)
    if state == OPEN:
        return
    s = settings_of(form)
    if s.closed_message:
        raise AppError(409, "forms.closed_message", message=s.closed_message)
    if state == NOT_YET_OPEN:
        raise AppError(409, f"{prefix}.not_open_yet", opens_at=s.opens_at.isoformat())
    raise AppError(409, f"{prefix}.closed_on", closes_at=s.closes_at.isoformat())


# --- who answered ------------------------------------------------------------------


def is_anonymous(form) -> bool:
    """Only questionnaires: an exam's results belong to the person who took it."""
    return form.type == "questionnaire" and settings_of(form).anonymous


def max_attempts(form) -> Optional[int]:
    return 1 if settings_of(form).one_response_per_person else form.max_attempts


def edit_window(form) -> Optional[timedelta]:
    """How long after submitting a response can still be changed; None when it can't."""
    minutes = settings_of(form).edit_window_minutes
    if form.type != "questionnaire" or not minutes:
        return None
    return timedelta(minutes=minutes)


def editable_until(form, submission) -> Optional[datetime]:
    window = edit_window(form)
    if window is None or submission.status not in ("submitted", "late") or submission.submitted_at is None:
        return None
    return submission.submitted_at + window


def can_edit(form, submission, now: Optional[datetime] = None) -> bool:
    until = editable_until(form, submission)
    return until is not None and (now or _now()) <= until


def respondent_key(form_id: int, kind: str, ident: Any) -> str:
    """A stand-in for a respondent on an anonymous form: the same for the same
    person on the same form, different on every other form, and not
    reversible without the server's secret."""
    return signing.keyed_hash(FormsEnv.FORM_LINK_SECRET, f"respondent:{form_id}:{kind}:{ident}")


# --- endings (T2.2.2) --------------------------------------------------------------


def last_section_on_path(form, visited: Optional[set[int]]) -> Optional[int]:
    """The section the respondent's path ended on (paths only move forward)."""
    if not visited or not form.sections:
        return None
    from .service import ordered_sections

    ordered = [s["id"] for s in ordered_sections(form.sections) if s["id"] in visited]
    return ordered[-1] if ordered else None


def pick_ending(form, *, score: Optional[float], last_section_id: Optional[int]) -> Optional[EndingScreen]:
    for ending in settings_of(form).endings:
        if ending.section_id is not None and ending.section_id != last_section_id:
            continue
        if ending.min_score is not None and (score is None or score < ending.min_score):
            continue
        if ending.max_score is not None and (score is None or score > ending.max_score):
            continue
        return ending
    return None


# --- shuffling (T2.2.9) ------------------------------------------------------------


def new_seed() -> int:
    return secrets.randbits(31)


def shuffled_order(form, seed: int) -> Optional[dict[str, Any]]:
    """The order one attempt is shown, from its seed: questions shuffled within
    their section (display blocks stay where they are), and choice options
    shuffled. None when the form shuffles nothing."""
    s = settings_of(form)
    if not (s.shuffle_questions or s.shuffle_options):
        return None
    rng = random.Random(seed)
    fields = sorted(form.fields, key=lambda f: (f.order, f.id))
    ids = [f.id for f in fields]
    if s.shuffle_questions:
        by_section: dict[Any, list[int]] = {}
        for i, f in enumerate(fields):
            if f.type not in DISPLAY_TYPES:
                by_section.setdefault(f.section_id, []).append(i)
        for positions in by_section.values():
            moved = [ids[i] for i in positions]
            rng.shuffle(moved)
            for i, fid in zip(positions, moved):
                ids[i] = fid
    options: dict[str, list[str]] = {}
    if s.shuffle_options:
        for f in fields:
            if f.type in CHOICE_TYPES and f.options and len(f.options) > 1:
                shuffled = list(f.options)
                rng.shuffle(shuffled)
                options[str(f.id)] = shuffled
    return {"seed": seed, "fields": ids, "options": options}


def apply_order(fields: list, order: Optional[dict[str, Any]]) -> None:
    """Puts respondent fields (RespondentField / PublicFormField) in an
    attempt's order, in place. Option pictures move with their options.
    Anything the order doesn't cover keeps its own place."""
    if not order:
        return
    position = {fid: i for i, fid in enumerate(order.get("fields") or [])}
    tail = len(position)
    for f in fields:
        f.order = position.get(f.id, tail + f.order)
        shuffled = (order.get("options") or {}).get(str(f.id))
        if not shuffled or not f.options or sorted(shuffled) != sorted(f.options):
            continue
        images = (f.config or {}).get("option_images")
        if images:
            by_option = dict(zip(f.options, images))
            f.config = {**f.config, "option_images": [by_option.get(o) for o in shuffled]}
        f.options = list(shuffled)


def attempt_token(form_id: int, seed: int) -> str:
    return signing.sign({"f": form_id, "s": seed}, purpose="attempt", secret=FormsEnv.FORM_LINK_SECRET)


def seed_from_attempt(form_id: int, token: Optional[str]) -> Optional[int]:
    data = signing.verify(token, purpose="attempt", secret=FormsEnv.FORM_LINK_SECRET)
    if not data or data.get("f") != form_id or not isinstance(data.get("s"), int):
        return None
    return data["s"]


# --- prefilled links (T2.2.7) ------------------------------------------------------

MAX_HIDDEN_VALUE_LENGTH = 500


@dataclass
class Prefill:
    # declared hidden fields only: stored with the response
    hidden: dict[str, str] = dataclass_field(default_factory=dict)
    # answers to start from (field id -> value); the respondent can change them
    answers: dict[str, Any] = dataclass_field(default_factory=dict)


def prefill_token(form_id: int, *, hidden: dict[str, str], answers: dict[str, Any],
                  expires_at: Optional[datetime]) -> str:
    return signing.sign(
        {"f": form_id, "h": hidden, "a": answers}, purpose="prefill", secret=FormsEnv.FORM_LINK_SECRET,
        expires_at=int(expires_at.timestamp()) if expires_at else None,
    )


def read_prefill(form, token: Optional[str], *, code: str) -> Optional[Prefill]:
    """The prefilled values of a link, or None without one. A forged, expired
    or foreign link raises `code`. Hidden keys the form no longer declares
    are dropped; answers are checked by the caller against the version."""
    if not token:
        return None
    data = signing.verify(token, purpose="prefill", secret=FormsEnv.FORM_LINK_SECRET)
    if not data or data.get("f") != form.id:
        raise AppError(422, code)
    declared = {h.key for h in settings_of(form).hidden_fields}
    hidden = data.get("h") if isinstance(data.get("h"), dict) else {}
    answers = data.get("a") if isinstance(data.get("a"), dict) else {}
    return Prefill(
        hidden={k: str(v)[:MAX_HIDDEN_VALUE_LENGTH] for k, v in hidden.items() if k in declared},
        answers={str(k): v for k, v in answers.items()},
    )


# --- resume and edit links (T2.2.5, T2.2.11) ---------------------------------------


def _stamp(at: Optional[datetime]) -> str:
    return f"{at.timestamp():.6f}" if at else "-"


def _submission_token(purpose: str, form_id: int, submission_id: int, at: Optional[datetime]) -> str:
    sig = signing.mac(FormsEnv.FORM_LINK_SECRET, f"{purpose}:{form_id}:{submission_id}:{_stamp(at)}")
    return f"{submission_id}.{sig}"


def token_submission_id(token: Any) -> Optional[int]:
    if not isinstance(token, str) or "." not in token or len(token) > 200:
        return None
    head = token.split(".", 1)[0]
    return int(head) if head.isdigit() else None


def resume_token(submission) -> str:
    return _submission_token("resume", submission.form_id, submission.id, submission.started_at)


def edit_token(submission) -> str:
    return _submission_token("edit", submission.form_id, submission.id, submission.submitted_at)


def token_matches(token: str, purpose: str, submission) -> bool:
    import hmac

    at = submission.started_at if purpose == "resume" else submission.submitted_at
    expected = _submission_token(purpose, submission.form_id, submission.id, at)
    return hmac.compare_digest(token, expected)
