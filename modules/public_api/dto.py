from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from modules.forms.dto import FormTheme, respondent_config
from modules.submissions.dto import EndingRead, RespondentSection, _theme_or_none


class PublicCustomer(BaseModel):
    email: EmailStr
    first_name: str = Field(min_length=1, max_length=120)
    last_name: str = Field(min_length=1, max_length=120)
    phone: Optional[str] = Field(default=None, max_length=32)


class PublicDraftCustomer(BaseModel):
    """Details typed so far, kept with a saved draft; checked on submit."""
    email: Optional[str] = Field(default=None, max_length=254)
    first_name: Optional[str] = Field(default=None, max_length=120)
    last_name: Optional[str] = Field(default=None, max_length=120)
    phone: Optional[str] = Field(default=None, max_length=32)


Token = Optional[str]


class _Respondent(BaseModel):
    # a signed prefilled link (T2.2.7)
    prefill: Token = Field(default=None, max_length=8192)
    # the attempt token GET /public/forms/{token} returned: the shuffled order shown (T2.2.9)
    attempt: Token = Field(default=None, max_length=512)
    # anonymous forms: a random id the browser keeps, so one response per
    # person holds without knowing who they are (T2.2.8)
    device_id: Optional[str] = Field(default=None, min_length=8, max_length=64, pattern=r"^[A-Za-z0-9_-]+$")
    # the CAPTCHA widget's answer (T2.2.6)
    captcha_token: Token = Field(default=None, max_length=4096)


class PublicSubmitRequest(_Respondent):
    # required unless the form is anonymous (then ignored)
    customer: Optional[PublicCustomer] = None
    answers: dict[str, Any]
    # finishes this saved draft (T2.2.5) instead of starting a new response
    resume_token: Token = Field(default=None, max_length=200)


class PublicDraftSave(_Respondent):
    customer: Optional[PublicDraftCustomer] = None
    answers: dict[str, Any] = Field(default_factory=dict)


class PublicDraftUpdate(BaseModel):
    customer: Optional[PublicDraftCustomer] = None
    answers: dict[str, Any] = Field(default_factory=dict)


class PublicEditRequest(BaseModel):
    answers: dict[str, Any]


class PublicFormField(BaseModel):
    """Form field as exposed publicly (no right_answer)."""
    model_config = ConfigDict(from_attributes=True)
    id: int
    question: str
    type: str
    options: Optional[list[str]] = None
    order: int
    help_text: Optional[str] = None
    is_required: bool
    section_id: Optional[int] = None
    # what rules call the question, and the rule that shows it (E2.3)
    key: Optional[str] = None
    visible_if: Optional[Any] = None
    config: Optional[dict[str, Any]] = None

    @field_validator("config")
    @classmethod
    def _declared_keys_only(cls, v, info):
        return respondent_config(info.data.get("type"), v)


class CaptchaWidget(BaseModel):
    provider: str
    site_key: str


class PublicForm(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    description: Optional[str] = None
    type: str
    fields: list[PublicFormField] = []
    # typed, so stored-only keys (score weights) never reach the public
    sections: Optional[list[RespondentSection]] = None
    theme: Optional[FormTheme] = None
    # links to the images the questions and the theme use, by file id
    media: dict[str, str] = {}

    # --- E2.2, filled in by the service ---
    # outside the form's dates no questions are served (T2.2.1)
    availability: Literal["open", "not_yet_open", "closed"] = "open"
    opens_at: Optional[datetime] = None
    closes_at: Optional[datetime] = None
    closed_message: Optional[str] = None
    # no contact details are asked for
    anonymous: bool = False
    allow_resume: bool = False
    show_progress: bool = False
    # how long a response can be changed after submitting, if at all
    edit_window_minutes: Optional[int] = None
    # show this widget and send its answer as captcha_token
    captcha: Optional[CaptchaWidget] = None
    # send back with the response, so it keeps the order shown
    attempt: Optional[str] = None
    # a prefilled link's starting answers
    prefill_answers: dict[str, Any] = {}
    # its hidden values that the form's rules read (E2.3)
    hidden: dict[str, Any] = {}

    @field_validator("theme", mode="before")
    @classmethod
    def _stored_theme(cls, v):
        return _theme_or_none(v)


class PublicSubmitResponse(BaseModel):
    # nothing about the customer record: whether an email was already known
    # must not be readable from the response
    submission_id: int
    ending: Optional[EndingRead] = None
    # the respondent may change the response with this until editable_until (T2.2.11)
    edit_token: Optional[str] = None
    editable_until: Optional[datetime] = None


class PublicDraftRead(BaseModel):
    """A saved draft's resume link token (T2.2.5): ?resume=<resume_token>."""
    resume_token: str
    expires_at: datetime


class PublicDraft(BaseModel):
    """A saved draft to carry on with, against the version it was started on."""
    form: PublicForm
    answers: dict[str, Any] = {}
    customer: Optional[PublicDraftCustomer] = None
    expires_at: Optional[datetime] = None


class PublicResponse(BaseModel):
    """A submitted response that can still be changed."""
    form: PublicForm
    answers: dict[str, Any] = {}
    editable_until: datetime
