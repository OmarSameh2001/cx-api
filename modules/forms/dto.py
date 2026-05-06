from datetime import datetime
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


FieldType = Literal["single_choice", "multi_choice", "boolean", "text", "date", "phone_number", "email", "file", "scale"]
SubmitterType = Literal["employee", "customer"]


class FormFieldBase(BaseModel):
    question: str = Field(min_length=1)
    type: FieldType
    options: Optional[list[str]] = None
    right_answer: Optional[str] = None
    order: int = 0
    help_text: Optional[str] = None
    is_required: bool = False
    score_weight: float = 0.0

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
        return v


class FormFieldCreate(FormFieldBase):
    pass


class FormFieldRead(FormFieldBase):
    model_config = ConfigDict(from_attributes=True)
    id: int


class FormBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    source_type: Optional[str] = None
    type: Optional[str] = None
    description: Optional[str] = None
    submitter_type: list[SubmitterType] = Field(min_length=1)
    assigned_to_units: Optional[list[int]] = None

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


class FormUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    source_type: Optional[str] = None
    type: Optional[str] = None
    description: Optional[str] = None
    submitter_type: Optional[list[SubmitterType]] = None
    assigned_to_units: Optional[list[int]] = None
    is_active: Optional[bool] = None
    is_archived: Optional[bool] = None
    fields: Optional[list[FormFieldCreate]] = None


class FormRead(FormBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    is_active: bool
    is_archived: bool
    created_at: datetime
    created_by: Optional[int]
    fields: list[FormFieldRead] = []


class FormSummary(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    type: Optional[str]
    is_active: bool
    is_archived: bool
    submitter_type: list[str]
    created_at: datetime
    created_by: Optional[int]
