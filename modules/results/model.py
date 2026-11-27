from datetime import date, datetime
from typing import Any, Optional

from sqlalchemy import (
    BigInteger, Boolean, Date, DateTime, Float, ForeignKey, Index, Integer, String, Text,
    UniqueConstraint, text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from db import Base


class SubmissionValue(Base):
    """One answer of a finished submission (E1.6), so results can be filtered,
    grouped and aggregated in SQL instead of by reading every answers blob.

    Written when a submission is submitted (or late), and rewritten when it
    is regraded. The submission's `answers` JSON stays the record of what was
    answered; these rows are derived from it and can always be rebuilt
    (`python scripts.py results:backfill`). Unanswered questions and
    questions on sections the respondent's path skipped have no row.
    """

    __tablename__ = "submission_values"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    submission_id: Mapped[int] = mapped_column(
        ForeignKey("submissions.id", ondelete="CASCADE"), nullable=False
    )
    organisation_id: Mapped[int] = mapped_column(
        ForeignKey("organisations.id", ondelete="CASCADE"), nullable=False
    )
    form_id: Mapped[int] = mapped_column(ForeignKey("forms.id", ondelete="CASCADE"), nullable=False)
    form_version_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("form_versions.id", ondelete="CASCADE"), index=True
    )
    # the question in the version answered: its id there, and the key that
    # stays the same from one version to the next (follow results by key)
    field_id: Mapped[int] = mapped_column(Integer, nullable=False)
    question_key: Mapped[str] = mapped_column(String(32), nullable=False)
    question_type: Mapped[str] = mapped_column(String(32), nullable=False)
    section_id: Mapped[Optional[int]] = mapped_column(Integer)

    # the answer, in the column for its type: choice, text and time answers
    # (and a scale's "na") in value_text; scale, NPS, rating, number, currency
    # and slider answers in value_number; yes/no in value_bool; dates in
    # value_date; multiple choice (a list of options), grids ({row: column},
    # {row: [columns]}) and files in value_json
    value_text: Mapped[Optional[str]] = mapped_column(Text)
    value_number: Mapped[Optional[float]] = mapped_column(Float)
    value_bool: Mapped[Optional[bool]] = mapped_column(Boolean)
    value_date: Mapped[Optional[date]] = mapped_column(Date)
    value_json: Mapped[Optional[Any]] = mapped_column(JSONB)

    # points earned and possible, for graded questions only (null otherwise)
    score: Mapped[Optional[float]] = mapped_column(Float)
    max_score: Mapped[Optional[float]] = mapped_column(Float)

    # who and where the answer is about. unit_id is the respondent's unit for
    # signed-in employees and null for public links, until submissions record
    # the employee and branch they are about (T2.5.1), which also fills
    # subject_employee_id.
    subject_employee_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("employees.id", ondelete="SET NULL")
    )
    unit_id: Mapped[Optional[int]] = mapped_column(ForeignKey("units.id", ondelete="SET NULL"))

    submitted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    # from start to submit; null for public links, which are answered in one request
    duration_seconds: Mapped[Optional[int]] = mapped_column(Integer)

    __table_args__ = (
        UniqueConstraint("submission_id", "field_id", name="uq_submission_values_submission_field"),
        # results of one form, per question, over time (the main query)
        Index("ix_submission_values_org_form_key_time",
              "organisation_id", "form_id", "question_key", "submitted_at"),
        # a manager's units across forms
        Index("ix_submission_values_org_unit_time", "organisation_id", "unit_id", "submitted_at"),
        Index("ix_submission_values_subject_time", "subject_employee_id", "submitted_at",
              postgresql_where=text("subject_employee_id IS NOT NULL")),
    )
