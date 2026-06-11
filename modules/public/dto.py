from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, EmailStr, Field


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


class PublicForm(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    description: Optional[str] = None
    type: str
    fields: list[PublicFormField] = []
    sections: Optional[list[dict]] = None


class PublicSubmitResponse(BaseModel):
    submission_id: int
    customer_id: int
    created_customer: bool
