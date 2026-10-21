"""What the model is asked to return.

This is deliberately easier for a model to fill than FormCreate: fields are
nested in their section, sections are referenced by their 1-based number and
branching is a list instead of a free-keyed dict. mapper.py turns it into the
FormCreate payload the form builder submits.
"""

from typing import Literal, Optional, Union

from pydantic import BaseModel, Field

from modules.forms.dto import FieldType, FormType, SubmitterType


SectionRef = Union[int, Literal["end"]]


class GeneratedBranch(BaseModel):
    answer: str = Field(
        description='The option text that triggers the jump; "true"/"false" for boolean questions.'
    )
    go_to: SectionRef = Field(
        description='1-based number of a LATER section, or "end" to finish the form.'
    )


class GeneratedField(BaseModel):
    question: str
    type: FieldType
    options: Optional[list[str]] = Field(
        default=None,
        description=(
            "single_choice/multi_choice: at least 2 distinct options. "
            "scale: exactly 2 labels [label for 1, label for 5] (may be empty strings). "
            "Omit for every other type."
        ),
    )
    right_answer: Optional[str] = Field(
        default=None,
        description=(
            "Exams only. single_choice: one option's exact text. multi_choice: comma-separated "
            'exact option texts. boolean: "true" or "false". text: a short reference answer. '
            "Omit for other types and for questionnaires."
        ),
    )
    help_text: Optional[str] = None
    is_required: bool = False
    score_weight: float = Field(
        default=0.0, ge=0, description="Exams only: points for a correct answer. 0 for questionnaires."
    )
    branching: Optional[list[GeneratedBranch]] = Field(
        default=None,
        description=(
            "Questionnaires with sections only, single_choice/boolean only, "
            "at most one branching question per section."
        ),
    )


class GeneratedSection(BaseModel):
    title: str
    description: Optional[str] = None
    score_weight: float = Field(default=1.0, gt=0, description="Exams only: section weight. 1 otherwise.")
    next_section: Optional[SectionRef] = Field(
        default=None,
        description='Where to go after this section when no branch applies: a LATER section number or "end". Omit for the next one.',
    )
    fields: list[GeneratedField] = Field(min_length=1)


class GeneratedForm(BaseModel):
    name: str
    description: Optional[str] = None
    type: FormType
    submitter_type: list[SubmitterType] = Field(min_length=1)
    time_limit_minutes: Optional[int] = Field(default=None, ge=1, description="Exams only.")
    max_attempts: Optional[int] = Field(default=None, ge=1)
    results_revealed: bool = False
    fields: list[GeneratedField] = Field(
        default_factory=list, description="Use for a form WITHOUT sections; leave empty when sections are used."
    )
    sections: list[GeneratedSection] = Field(
        default_factory=list, description="Use for a form WITH sections; leave empty otherwise."
    )
