from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

from modules.forms.dto import FormTheme, SectionTarget, respondent_config
from modules.submissions.dto import RespondentSection, _theme_or_none


class PublicCustomer(BaseModel):
    email: EmailStr
    first_name: str = Field(min_length=1, max_length=120)
    last_name: str = Field(min_length=1, max_length=120)
    phone: Optional[str] = Field(default=None, max_length=32)


class PublicSubmitRequest(BaseModel):
    customer: PublicCustomer
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
    branching: Optional[dict[str, SectionTarget]] = None
    config: Optional[dict[str, Any]] = None

    @field_validator("config")
    @classmethod
    def _declared_keys_only(cls, v, info):
        return respondent_config(info.data.get("type"), v)


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

    @field_validator("theme", mode="before")
    @classmethod
    def _stored_theme(cls, v):
        return _theme_or_none(v)


class PublicSubmitResponse(BaseModel):
    # nothing about the customer record: whether an email was already known
    # must not be readable from the response
    submission_id: int
