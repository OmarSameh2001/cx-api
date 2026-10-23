from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict

from modules.forms.dto import SectionTarget


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
    submitter_name: Optional[str] = None


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
    # on a section the respondent's branching path skipped (finalized
    # submissions only): the question was never shown, not left unanswered
    skipped: bool = False


class SubmissionDetail(SubmissionRead):
    answers: Optional[dict[str, Any]] = None
    fields: list[SubmissionDetailField] = []


class RespondentField(BaseModel):
    """A question as the respondent sees it: no correct answer, no grading."""
    model_config = ConfigDict(from_attributes=True)
    id: int
    question: str
    type: str
    options: Optional[list[str]] = None
    order: int
    help_text: Optional[str] = None
    is_required: bool
    section_id: Optional[int] = None
    branching: Optional[dict[str, SectionTarget]] = None


class RespondentSection(BaseModel):
    # only what paging needs; score weights stay with the reviewers
    id: int
    title: str
    description: Optional[str] = None
    order: int = 0
    next_section_id: Optional[SectionTarget] = None


class RespondentForm(BaseModel):
    """The form a respondent is filling in, served through their own
    in-progress submission so questions can't be read before starting."""
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    description: Optional[str] = None
    type: str
    time_limit_minutes: Optional[int] = None
    max_attempts: Optional[int] = None
    fields: list[RespondentField] = []
    sections: Optional[list[RespondentSection]] = None
