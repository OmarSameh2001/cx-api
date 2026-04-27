from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict


class SubmissionCreate(BaseModel):
    form_id: int
    answers: dict[str, Any]


class SubmissionUpdate(BaseModel):
    answers: dict[str, Any]


class SubmissionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    form_id: int
    answers: Optional[dict[str, Any]]
    score: Optional[float]
    submitted_at: datetime
    customer_id: Optional[int]
    user_id: Optional[int]
