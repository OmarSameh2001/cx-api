from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


FieldType = Literal[
    "single_choice",
    "multi_choice",
    "boolean",
    "text",
    "date",
    "phone_number",
    "email",
    "file",
    "scale",
]
SubmitterType = Literal["employee", "customer"]
FormType = Literal["questionnaire", "exam"]

AUTO_GRADABLE_TYPES = {"single_choice", "multi_choice", "boolean"}


class FormSectionPayload(BaseModel):
    id: int
    title: str = Field(min_length=1, max_length=255)
    description: Optional[str] = None
    order: int = 0
    score_weight: float = Field(default=1.0, gt=0)


class FormFieldBase(BaseModel):
    question: str = Field(min_length=1)
    type: FieldType
    options: Optional[list[str]] = None
    right_answer: Optional[str] = None
    order: int = 0
    help_text: Optional[str] = None
    is_required: bool = False
    score_weight: float = 0.0
    section_id: Optional[int] = None

    @field_validator("options")
    @classmethod
    def _validate_options(cls, v, info):
        type_ = info.data.get("type")
        if type_ in ("single_choice", "multi_choice"):
            if not v or len(v) < 2:
                raise ValueError(f"{type_} fields require at least 2 options")
        return v

    @field_validator("right_answer")
    @classmethod
    def _validate_right_answer(cls, v, info):
        type_ = info.data.get("type")
        if type_ == "text":
            return None
        if v is None:
            return v
        options = info.data.get("options") or []
        if type_ == "single_choice":
            if v not in options:
                raise ValueError("right_answer must be one of options for single_choice")
        elif type_ == "multi_choice":
            parts = {p.strip() for p in v.split(",") if p.strip()}
            if not parts:
                raise ValueError("right_answer must list at least one option for multi_choice")
            if not parts.issubset(set(options)):
                raise ValueError("right_answer values must all be in options for multi_choice")
        elif type_ == "boolean":
            if v.strip().lower() not in {"true", "false"}:
                raise ValueError("right_answer for boolean must be 'true' or 'false'")
        return v


class FormFieldCreate(FormFieldBase):
    pass


class FormFieldRead(FormFieldBase):
    model_config = ConfigDict(from_attributes=True)
    id: int


class FormBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    source_type: Optional[str] = None
    type: FormType = "questionnaire"
    description: Optional[str] = None
    submitter_type: list[SubmitterType] = Field(min_length=1)
    assigned_to_units: Optional[list[int]] = None
    time_limit_minutes: Optional[int] = Field(default=None, ge=1)
    max_attempts: Optional[int] = Field(default=None, ge=1)
    results_revealed: bool = False

    @field_validator("submitter_type")
    @classmethod
    def _unique(cls, v):
        return list(dict.fromkeys(v))

    @field_validator("assigned_to_units")
    @classmethod
    def _unique_units(cls, v):
        if v is None:
            return v
        return list(dict.fromkeys(v))


class FormCreate(FormBase):
    fields: list[FormFieldCreate] = Field(min_length=1)
    sections: Optional[list[FormSectionPayload]] = None

    @model_validator(mode="after")
    def _validate_constraints(self):
        if self.sections:
            section_ids = {s.id for s in self.sections}
            if any(f.section_id is None for f in self.fields):
                raise ValueError("all fields must have a section_id when sections are defined")
            bad = [f.section_id for f in self.fields if f.section_id not in section_ids]
            if bad:
                raise ValueError(f"fields reference unknown section ids: {bad}")
        else:
            if any(f.section_id is not None for f in self.fields):
                raise ValueError("section_id on fields requires sections to be defined")
        if self.type == "exam":
            if not any(f.type in AUTO_GRADABLE_TYPES for f in self.fields):
                raise ValueError("exam forms must contain at least one auto-gradable field")
            if self.max_attempts is None:
                self.max_attempts = 1
        return self


class FormUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    source_type: Optional[str] = None
    type: Optional[FormType] = None
    description: Optional[str] = None
    submitter_type: Optional[list[SubmitterType]] = None
    assigned_to_units: Optional[list[int]] = None
    time_limit_minutes: Optional[int] = Field(default=None, ge=1)
    max_attempts: Optional[int] = Field(default=None, ge=1)
    results_revealed: Optional[bool] = None
    is_active: Optional[bool] = None
    is_archived: Optional[bool] = None
    fields: Optional[list[FormFieldCreate]] = None
    sections: Optional[list[FormSectionPayload]] = None

    @model_validator(mode="after")
    def _validate_sections(self):
        if self.sections is not None and self.fields is not None:
            section_ids = {s.id for s in self.sections}
            if any(f.section_id is None for f in self.fields):
                raise ValueError("all fields must have a section_id when sections are defined")
            bad = [f.section_id for f in self.fields if f.section_id not in section_ids]
            if bad:
                raise ValueError(f"fields reference unknown section ids: {bad}")
        elif self.sections is None and self.fields is not None:
            if any(f.section_id is not None for f in self.fields):
                raise ValueError("section_id on fields requires sections to be defined")
        return self


class FormRead(FormBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    is_active: bool
    is_archived: bool
    public_token: Optional[str] = None
    created_at: datetime
    created_by: Optional[int]
    fields: list[FormFieldRead] = []
    sections: Optional[list[dict]] = None


class FormSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    type: str
    is_active: bool
    is_archived: bool
    submitter_type: list[str]
    assigned_to_units: Optional[list[int]] = None
    time_limit_minutes: Optional[int] = None
    max_attempts: Optional[int] = None
    results_revealed: bool = False
    created_at: datetime
    created_by: Optional[int]


MyStatus = Literal["not_started", "in_progress", "submitted", "late", "expired"]


class AssignedFormSummary(FormSummary):
    my_status: MyStatus = "not_started"
    attempts_used: int = 0
