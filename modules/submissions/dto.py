from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict


SubmissionStatusT = Literal["in_progress", "submitted", "late", "expired"]


class SubmissionStartRequest(BaseModel):
    form_id: int


class SubmissionDraftUpdate(BaseModel):
    answers: dict[str, Any]


class SubmissionFinalize(BaseModel):
    answers: Optional[dict[str, Any]] = None


class SubmissionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    form_id: int
    status: SubmissionStatusT
    started_at: datetime
    expires_at: Optional[datetime]
    submitted_at: Optional[datetime]
    attempt_number: int
    results_revealed: bool
    score: Optional[float]
    customer_id: Optional[int]
    user_id: Optional[int]


class SubmissionDetailField(BaseModel):
    """A form field as exposed in a submission detail; sensitive bits are
    optional and only filled by the service when the caller is allowed to see
    them (reveal-gated)."""
    model_config = ConfigDict(from_attributes=True)
    id: int
    order: int
    type: str
    is_required: bool
    score_weight: float
    question: Optional[str] = None
    options: Optional[list[str]] = None
    right_answer: Optional[str] = None
    help_text: Optional[str] = None


class SubmissionDetail(SubmissionRead):
    answers: Optional[dict[str, Any]] = None
    fields: list[SubmissionDetailField] = []
