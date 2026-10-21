from typing import Optional

from pydantic import BaseModel, Field

from modules.forms.dto import FormType, SubmitterType


class FormGenerateRequest(BaseModel):
    prompt: str = Field(min_length=3, max_length=4000)
    # left empty, the model picks from the prompt
    type: Optional[FormType] = None
    submitter_type: Optional[list[SubmitterType]] = Field(default=None, min_length=1)
    language: Optional[str] = Field(default=None, max_length=64)
    max_questions: int = Field(default=15, ge=1, le=50)
