"""Shape and size checks for answer values, per question type.

Answers arrive as free JSON keyed by field id. Unknown keys are dropped before
this runs (see `_prune_to_path`); this rejects values that a question could
never produce, and bounds their size so a submission can't grow without limit.
Empty values pass here: whether one is allowed is `_validate_required`'s call.
"""

import math
import re
from datetime import date
from typing import Any, Optional

from pydantic import EmailStr, TypeAdapter, ValidationError

from common.errors import AppError
from modules.forms.dto import DISPLAY_TYPES, GRID_TYPES, MAX_LONG_TEXT_LENGTH, read_config
from modules.forms.model import Form, FormField

MAX_TEXT_LENGTH = 5000
MAX_SHORT_LENGTH = 255
# a scale answer that isn't a point (when the scale allows it)
NOT_APPLICABLE = "na"
_TIME = re.compile(r"^([01][0-9]|2[0-3]):[0-5][0-9]$")

_FILE_ANSWER_KEYS = {"file_id", "token", "name", "content_type", "size"}
_EMAIL = TypeAdapter(EmailStr)
_PHONE = re.compile(r"^\+?[0-9 ()\-.]{3,32}$")


def _is_empty(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def as_number(value: Any) -> Optional[float]:
    """A number answer as a float: a JSON number, or the text of one."""
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
    elif isinstance(value, str) and value.strip():
        try:
            number = float(value.strip())
        except ValueError:
            return None
    else:
        return None
    return number if math.isfinite(number) else None


def _whole(value: Any) -> Optional[int]:
    number = as_number(value)
    if number is None or number != int(number):
        return None
    return int(number)


def is_incomplete(field: Any, value: Any) -> bool:
    """A required question without an answer. A grid needs every row."""
    if _is_empty(value):
        return True
    if field.type in GRID_TYPES:
        config = read_config(field.type, field.config)
        if config is None or not isinstance(value, dict):
            return True
        return any(_is_empty(value.get(row)) for row in config.rows)
    return False


def _range_problem(number: float, low: Optional[float], high: Optional[float]) -> Optional[str]:
    if low is not None and number < low:
        return f"must be at least {low:g}"
    if high is not None and number > high:
        return f"must be at most {high:g}"
    return None


def _choice_problem(value: Any, options: list[str], *, multiple: bool) -> Optional[str]:
    if not multiple:
        return None if isinstance(value, str) and value in options else "must be one of the options"
    parts = value.split(",") if isinstance(value, str) else value
    if not isinstance(parts, list) or not all(isinstance(p, str) for p in parts):
        return "must be a list of options"
    parts = [p.strip() for p in parts if p.strip()]
    if len(parts) != len(set(parts)) or not set(parts) <= set(options):
        return "must be distinct options"
    return None


def _grid_problem(field: Any, value: Any) -> Optional[str]:
    config = read_config(field.type, field.config)
    if config is None:
        return "can't be answered: the question has no rows and columns"
    if not isinstance(value, dict) or set(value) - set(config.rows):
        return "must give answers for the question's rows"
    for answer in value.values():
        if _is_empty(answer):
            continue
        if field.type == "checkbox_grid":
            ok = (
                isinstance(answer, list)
                and all(isinstance(a, str) and a in config.columns for a in answer)
                and len(answer) == len(set(answer))
            )
        else:
            ok = isinstance(answer, str) and answer in config.columns
        if not ok:
            return "must pick columns of the question"
    return None


def point_range(field: Any) -> tuple[int, int]:
    """The lowest and highest point of a scale, NPS or rating question."""
    if field.type == "nps":
        return 0, 10
    config = read_config(field.type, field.config)
    if field.type == "rating":
        return 1, config.levels if config else 5
    return (config.min, config.max) if config else (1, 5)


def _problem(field: FormField, value: Any, *, draft: bool) -> str | None:
    """Why `value` can't be an answer to `field`, or None if it can."""
    options = field.options or []
    type_ = field.type
    if type_ in DISPLAY_TYPES:
        return "can't be answered"
    if type_ in ("single_choice", "dropdown"):
        return _choice_problem(value, options, multiple=False)
    if type_ == "multi_choice":
        return _choice_problem(value, options, multiple=True)
    if type_ == "image_choice":
        config = read_config(type_, field.config)
        return _choice_problem(value, options, multiple=bool(config and config.multiple))
    if type_ in GRID_TYPES:
        return _grid_problem(field, value)
    if type_ == "boolean":
        ok = isinstance(value, bool) or (
            isinstance(value, str) and value.strip().lower() in ("true", "false")
        )
        return None if ok else "must be true or false"
    if type_ == "file":
        # {"file_id": 12} from the upload, plus "token" for public respondents;
        # stored answers also carry name, content_type and size
        if not isinstance(value, dict) or set(value) - _FILE_ANSWER_KEYS:
            return "must be an uploaded file"
        file_id = value.get("file_id")
        if not isinstance(file_id, int) or isinstance(file_id, bool) or file_id <= 0:
            return "must be an uploaded file"
        token = value.get("token")
        if token is not None and (not isinstance(token, str) or len(token) > 128):
            return "has an invalid file token"
        return None
    if type_ in ("scale", "nps", "rating"):
        low, high = point_range(field)
        if type_ == "scale" and value == NOT_APPLICABLE:
            config = read_config(type_, field.config)
            if config is not None and config.allow_na:
                return None
        point = _whole(value)
        ok = point is not None and low <= point <= high
        return None if ok else f"must be a whole number from {low} to {high}"
    if type_ in ("number", "currency", "slider"):
        number = as_number(value)
        if number is None:
            return "must be a number"
        config = read_config(type_, field.config)
        if config is None:
            return None
        if type_ == "currency" and abs(number * 100 - round(number * 100)) > 1e-6:
            return "must have at most 2 decimal places"
        if type_ == "number" and config.integer_only and number != int(number):
            return "must be a whole number"
        if type_ == "slider":
            steps = (number - config.min) / config.step
            if abs(steps - round(steps)) > 1e-6:
                return f"must be a step of {config.step:g} from {config.min:g}"
        low = config.min
        if type_ == "currency" and low is None:
            low = 0  # amounts are never negative
        return _range_problem(number, low, config.max)
    if not isinstance(value, str):
        return "must be text"
    if type_ == "text":
        return None if len(value) <= MAX_TEXT_LENGTH else f"must be at most {MAX_TEXT_LENGTH} characters"
    if type_ == "long_text":
        config = read_config(type_, field.config)
        limit = (config.max_length if config else None) or MAX_LONG_TEXT_LENGTH
        return None if len(value) <= limit else f"must be at most {limit} characters"
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
    elif type_ == "time":
        if not _TIME.match(value):
            return "must be a time (HH:MM, 24-hour)"
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
            raise AppError(422, "submissions.answer_invalid", question=field.question, problem=problem)
