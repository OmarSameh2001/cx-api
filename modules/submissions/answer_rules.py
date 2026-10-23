"""Shape and size checks for answer values, per question type.

Answers arrive as free JSON keyed by field id. Unknown keys are dropped before
this runs (see `_prune_to_path`); this rejects values that a question could
never produce, and bounds their size so a submission can't grow without limit.
Empty values pass here: whether one is allowed is `_validate_required`'s call.
"""

import re
from datetime import date
from typing import Any

from fastapi import HTTPException, status
from pydantic import EmailStr, TypeAdapter, ValidationError

from modules.forms.model import Form, FormField

MAX_TEXT_LENGTH = 5000
MAX_SHORT_LENGTH = 255
SCALE_POINTS = 5  # the answer widget offers 1..5

_EMAIL = TypeAdapter(EmailStr)
_PHONE = re.compile(r"^\+?[0-9 ()\-.]{3,32}$")


def _is_empty(value: Any) -> bool:
    return value is None or value == "" or value == []


def _problem(field: FormField, value: Any, *, draft: bool) -> str | None:
    """Why `value` can't be an answer to `field`, or None if it can."""
    options = field.options or []
    type_ = field.type
    if type_ == "single_choice":
        return None if isinstance(value, str) and value in options else "must be one of the options"
    if type_ == "multi_choice":
        parts = value.split(",") if isinstance(value, str) else value
        if not isinstance(parts, list) or not all(isinstance(p, str) for p in parts):
            return "must be a list of options"
        parts = [p.strip() for p in parts if p.strip()]
        if len(parts) != len(set(parts)) or not set(parts) <= set(options):
            return "must be distinct options"
        return None
    if type_ == "boolean":
        ok = isinstance(value, bool) or (
            isinstance(value, str) and value.strip().lower() in ("true", "false")
        )
        return None if ok else "must be true or false"
    if type_ == "scale":
        ok = isinstance(value, int) and not isinstance(value, bool) and 1 <= value <= SCALE_POINTS
        if isinstance(value, str) and value.isdigit():
            ok = 1 <= int(value) <= SCALE_POINTS
        return None if ok else f"must be a whole number from 1 to {SCALE_POINTS}"
    if not isinstance(value, str):
        return "must be text"
    if type_ == "text":
        return None if len(value) <= MAX_TEXT_LENGTH else f"must be at most {MAX_TEXT_LENGTH} characters"
    if len(value) > MAX_SHORT_LENGTH:
        return f"must be at most {MAX_SHORT_LENGTH} characters"
    if draft:
        # autosave runs mid-typing; formats are checked on submit
        return None
    if type_ == "date":
        try:
            date.fromisoformat(value)
        except ValueError:
            return "must be a date (YYYY-MM-DD)"
    elif type_ == "email":
        try:
            _EMAIL.validate_python(value)
        except ValidationError:
            return "must be an email address"
    elif type_ == "phone_number":
        if not _PHONE.match(value):
            return "must be a phone number"
    return None


def validate_answer_values(
    form: Form, answers: dict[str, Any], *, draft: bool = False
) -> None:
    by_id = {str(f.id): f for f in form.fields}
    for key, value in answers.items():
        field = by_id.get(key)
        if field is None or _is_empty(value):
            continue
        problem = _problem(field, value, draft=draft)
        if problem:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"Answer to \"{field.question}\" {problem}",
            )
