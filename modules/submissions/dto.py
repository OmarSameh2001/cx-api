from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

from modules.forms.dto import FormTheme, SectionTarget, respondent_config


SubmissionStatusT = Literal["in_progress", "submitted", "late", "expired"]


def _theme_or_none(v: Any) -> Optional[FormTheme]:
    """A stored theme that no longer fits is left out rather than break the form."""
    if v is None or isinstance(v, FormTheme):
        return v
    try:
        return FormTheme.model_validate(v)
    except ValueError:
        return None


class SubmissionStartRequest(BaseModel):
    form_id: int
    # a signed prefilled link's token (T2.2.7); used when a new attempt starts
    prefill: Optional[str] = Field(default=None, max_length=8192)


class SubmissionEdit(BaseModel):
    """A submitted response's new answers, all of them (T2.2.11)."""
    answers: dict[str, Any]


class EndingRead(BaseModel):
    """The ending screen a response earned (T2.2.2)."""
    model_config = ConfigDict(from_attributes=True)
    id: int
    title: str
    message: Optional[str] = None
    redirect_url: Optional[str] = None


class SubmissionDraftUpdate(BaseModel):
    answers: dict[str, Any]


class SubmissionFinalize(BaseModel):
    answers: Optional[dict[str, Any]] = None


class SubmissionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    form_id: int
    # the published version answered
    form_version_id: Optional[int] = None
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
    # E2.2: the respondent may change it until then (owners only)
    editable_until: Optional[datetime] = None
    edited_at: Optional[datetime] = None
    # the ending screen, on the response to submit only
    ending: Optional[EndingRead] = None
    # on an anonymous form nobody's id is stored
    anonymous: bool = False


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
    # what the answer means: scale range, grid rows and columns, images
    config: Optional[dict[str, Any]] = None
    # on a section the respondent's branching path skipped (finalized
    # submissions only): the question was never shown, not left unanswered
    skipped: bool = False


class SubmissionContact(BaseModel):
    email: str
    first_name: str
    last_name: str
    phone: Optional[str] = None


class SubmissionDetail(SubmissionRead):
    # public submissions: the contact details as given with this submission
    contact: Optional[SubmissionContact] = None
    # values from the prefilled link (reviewers only)
    hidden_fields: Optional[dict[str, Any]] = None
    answers: Optional[dict[str, Any]] = None
    # how the score was reached: section scores and points per question
    # (reveal-gated like the score)
    scores: Optional[dict[str, Any]] = None
    fields: list[SubmissionDetailField] = []
    # links to the images the questions use, by file id
    media: dict[str, str] = {}


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
    config: Optional[dict[str, Any]] = None

    @field_validator("config")
    @classmethod
    def _declared_keys_only(cls, v, info):
        return respondent_config(info.data.get("type"), v)


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
    theme: Optional[FormTheme] = None
    # links to the images the questions and the theme use, by file id
    media: dict[str, str] = {}
    # E2.2: filled in from the form's settings by respondent_extras
    show_progress: bool = False
    anonymous: bool = False

    @field_validator("theme", mode="before")
    @classmethod
    def _stored_theme(cls, v):
        return _theme_or_none(v)
