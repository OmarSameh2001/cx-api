from datetime import datetime
from typing import Literal, Optional, Union

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
BRANCHABLE_TYPES = {"single_choice", "boolean"}

# A jump target: a section id, or "end" to finish the form.
SectionTarget = Union[int, Literal["end"]]


class FormSectionPayload(BaseModel):
    id: int
    title: str = Field(min_length=1, max_length=255)
    description: Optional[str] = None
    order: int = 0
    score_weight: float = Field(default=1.0, gt=0)
    # where to go after this section when no branching answer applies;
    # None means the next section by order
    next_section_id: Optional[SectionTarget] = None


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
    # answer -> section to jump to; only for single_choice / boolean
    branching: Optional[dict[str, SectionTarget]] = None


class FormFieldCreate(FormFieldBase):
    # on update: existing field id to edit in place; omit for a new field
    id: Optional[int] = None

    # The rules below run on writes only. FormFieldRead serves what is stored,
    # so a row that predates a rule (or was fixed by hand) can't break reads.

    @field_validator("branching")
    @classmethod
    def _validate_branching(cls, v, info):
        if not v:
            return None
        type_ = info.data.get("type")
        if type_ not in BRANCHABLE_TYPES:
            raise ValueError("branching is only allowed on single_choice and boolean fields")
        if type_ == "boolean":
            v = {k.strip().lower(): t for k, t in v.items()}
            allowed = {"true", "false"}
        elif "options" not in info.data:
            # options already failed validation; that error is the useful one
            return v
        else:
            allowed = set(info.data.get("options") or [])
        bad = [k for k in v if k not in allowed]
        if bad:
            raise ValueError(f"branching keys must be valid answers, got: {bad}")
        return v

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
        if v is None:
            return v
        if type_ == "text":
            # the reference answer free text is scored against (BM25 +
            # semantic similarity); blank means the question isn't graded
            return v.strip() or None
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
            # a text question counts once it has a reference answer to score against
            if not any(
                f.type in AUTO_GRADABLE_TYPES or (f.type == "text" and f.right_answer)
                for f in self.fields
            ):
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
    # a response has been submitted (drafts don't count): structure is
    # locked, only wording can be changed. Filled in by the controller.
    has_submissions: bool = False


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
