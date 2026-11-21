from datetime import datetime
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

GroupBy = Literal[
    "question_key", "question_type", "section_id", "form_id", "form_version_id",
    "unit_id", "subject_employee_id",
    # the answer itself: an option, yes/no, a scale point (one row per option
    # picked in a multiple-choice answer)
    "value",
    # submitted time, truncated in UTC; the row's key is "period"
    "day", "week", "month",
]
Measure = Literal[
    # answers (options, when grouped by value), and distinct submissions
    "count", "submissions",
    # over number answers (scales)
    "avg_number", "min_number", "max_number", "sum_number",
    # over graded questions: average points, and points earned as a % of possible
    "avg_score", "score_percent",
]
_TIME_BUCKETS = {"day", "week", "month"}


class ResultsFilters(BaseModel):
    form_version_ids: Optional[list[int]] = Field(default=None, max_length=100)
    question_keys: Optional[list[str]] = Field(default=None, max_length=200)
    # within the units the caller may see; answers without a unit (public
    # links) are left out whenever units are given
    unit_ids: Optional[list[int]] = Field(default=None, max_length=500)
    subject_employee_ids: Optional[list[int]] = Field(default=None, max_length=500)
    # submitted_from <= submitted_at < submitted_to
    submitted_from: Optional[datetime] = None
    submitted_to: Optional[datetime] = None

    @field_validator("question_keys")
    @classmethod
    def _short_keys(cls, v):
        if v and any(len(k) > 32 for k in v):
            raise ValueError("question keys are at most 32 characters")
        return v

    @model_validator(mode="after")
    def _ordered_dates(self):
        if self.submitted_from and self.submitted_to and self.submitted_from >= self.submitted_to:
            raise ValueError("submitted_from must be before submitted_to")
        return self


class ResultsQuery(BaseModel):
    """Answers of finished submissions, filtered, grouped and aggregated.
    Always limited to the caller's organisation, and to their units unless
    they may see the whole organisation's results (see results.service)."""
    form_id: Optional[int] = None
    filters: ResultsFilters = Field(default_factory=ResultsFilters)
    group_by: list[GroupBy] = Field(default_factory=lambda: ["question_key"], max_length=4)
    measures: list[Measure] = Field(default_factory=lambda: ["count", "submissions"], min_length=1)
    limit: int = Field(default=1000, ge=1, le=5000)

    @model_validator(mode="after")
    def _distinct(self):
        if len(set(self.group_by)) != len(self.group_by):
            raise ValueError("group_by has a repeated entry")
        if len(set(self.measures)) != len(self.measures):
            raise ValueError("measures has a repeated entry")
        if len(_TIME_BUCKETS & set(self.group_by)) > 1:
            raise ValueError("group_by takes one of day, week and month")
        return self


class ResultsResponse(BaseModel):
    # one per group: the group_by values ("period" for a time bucket) and the measures
    rows: list[dict[str, Any]]
    # more groups matched than `limit`
    truncated: bool
    # what the caller's results cover: the whole organisation, or their units
    scope: Literal["organisation", "units"]
