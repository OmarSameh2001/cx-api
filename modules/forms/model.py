import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any, List, Optional

from sqlalchemy import (
    Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint, func, text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from db import Base

if TYPE_CHECKING:
    from ..employees.model import Employee
    from ..submissions.model import Submission
    from ..organisations.model import Organisation

class Form(Base):
    __tablename__ = "forms"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    source_type: Mapped[Optional[str]] = mapped_column(String(64))
    type: Mapped[str] = mapped_column(
        String(32), nullable=False, default="questionnaire", server_default="questionnaire"
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_archived: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    submitter_type: Mapped[Optional[list[str]]] = mapped_column(ARRAY(String(64)), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text)
    # validated against FormSettings (dto) on every write; keys a row lacks
    # read as that setting's default
    settings: Mapped[dict] = mapped_column(
        JSONB, default=dict, server_default=text("'{}'::jsonb"), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_by: Mapped[Optional[int]] = mapped_column(ForeignKey("employees.id"))
    organisation_id: Mapped[int] = mapped_column(
        ForeignKey("organisations.id"), nullable=False
    )
    assigned_to_units: Mapped[Optional[list[int]]] = mapped_column(ARRAY(Integer))
    public_token: Mapped[Optional[str]] = mapped_column(String(64), unique=True, index=True)
    sections: Mapped[Optional[list[dict]]] = mapped_column(JSONB, nullable=True)
    # The published version respondents get. `fields` and `sections` above
    # are the draft: editing them changes nothing until the next publish.
    current_version_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("form_versions.id", ondelete="SET NULL", use_alter=True,
                   name="fk_forms_current_version_id"),
    )

    organisations: Mapped["Organisation"] = relationship(foreign_keys=[organisation_id])
    creator: Mapped[Optional["Employee"]] = relationship(foreign_keys=[created_by])
    fields: Mapped[List["FormField"]] = relationship(
        back_populates="form", cascade="all, delete-orphan", order_by="FormField.order"
    )
    submissions: Mapped[List["Submission"]] = relationship(back_populates="form")
    # post_update: forms and form_versions point at each other
    current_version: Mapped[Optional["FormVersion"]] = relationship(
        foreign_keys=[current_version_id], post_update=True,
    )

    __table_args__ = (
        Index("ix_forms_org_active_archived", "organisation_id", "is_active", "is_archived"),
    )

    # The settings the engine reads, with FormSettings' defaults. A setter
    # replaces the dict so SQLAlchemy sees the change (JSONB isn't mutable-tracked).
    def _setting(self, key: str, default=None):
        return (self.settings or {}).get(key, default)

    def _set_setting(self, key: str, value) -> None:
        self.settings = {**(self.settings or {}), key: value}

    @property
    def time_limit_minutes(self) -> Optional[int]:
        return self._setting("time_limit_minutes")

    @time_limit_minutes.setter
    def time_limit_minutes(self, value: Optional[int]) -> None:
        self._set_setting("time_limit_minutes", value)

    @property
    def max_attempts(self) -> Optional[int]:
        return self._setting("max_attempts")

    @max_attempts.setter
    def max_attempts(self, value: Optional[int]) -> None:
        self._set_setting("max_attempts", value)

    @property
    def results_revealed(self) -> bool:
        return bool(self._setting("results_revealed", False))

    @results_revealed.setter
    def results_revealed(self, value: bool) -> None:
        self._set_setting("results_revealed", bool(value))

    @property
    def theme(self) -> Optional[dict]:
        """Cover, background and colours of the respondent view (T2.1.15)."""
        theme = self._setting("theme")
        return theme if isinstance(theme, dict) else None


class FormField(Base):
    __tablename__ = "form_fields"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    # Stable across versions: kept while the question is edited in place, so
    # results can be followed from one version to the next (a new type gets
    # a new key: its answers aren't comparable). Answers are keyed by id.
    key: Mapped[str] = mapped_column(String(32), nullable=False, default=lambda: new_field_key())
    question: Mapped[str] = mapped_column(Text, nullable=False)
    options: Mapped[Optional[list[str]]] = mapped_column(ARRAY(String(255)))
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    right_answer: Mapped[Optional[str]] = mapped_column(Text)
    order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    help_text: Mapped[Optional[str]] = mapped_column(Text)
    is_required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    score_weight: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)

    form_id: Mapped[int] = mapped_column(ForeignKey("forms.id"), nullable=False, index=True)
    section_id: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    branching: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)
    # per-type settings, validated by QUESTION_CONFIG_SCHEMAS (dto) on write
    config: Mapped[Optional[dict]] = mapped_column(JSONB, nullable=True)

    form: Mapped["Form"] = relationship(back_populates="fields")

    __table_args__ = (UniqueConstraint("form_id", "key", name="uq_form_fields_form_key"),)


def new_field_key() -> str:
    return uuid.uuid4().hex


class FormVersion(Base):
    """A form's structure as published: what respondents answered and what
    their submissions are checked, scored and shown against."""

    __tablename__ = "form_versions"

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    form_id: Mapped[int] = mapped_column(
        ForeignKey("forms.id", ondelete="CASCADE"), nullable=False, index=True
    )
    number: Mapped[int] = mapped_column(Integer, nullable=False)
    # {"type", "sections", "fields": [{id, key, question, type, options,
    # right_answer, order, help_text, is_required, score_weight, section_id,
    # branching, config}]}, built by forms.service.snapshot_of
    snapshot: Mapped[dict] = mapped_column(JSONB, nullable=False)
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    published_by: Mapped[Optional[int]] = mapped_column(
        ForeignKey("employees.id", ondelete="SET NULL")
    )

    __table_args__ = (UniqueConstraint("form_id", "number", name="uq_form_versions_form_number"),)


SNAPSHOT_FIELD_ATTRS = (
    "id", "key", "question", "type", "options", "right_answer", "order", "help_text",
    "is_required", "score_weight", "section_id", "branching", "config",
)


@dataclass(frozen=True)
class VersionField:
    """A question as one version published it; reads like a FormField."""
    id: int
    key: Optional[str] = None
    question: str = ""
    type: str = "text"
    options: Optional[list[str]] = None
    right_answer: Optional[str] = None
    order: int = 0
    help_text: Optional[str] = None
    is_required: bool = False
    score_weight: float = 0.0
    section_id: Optional[int] = None
    branching: Optional[dict] = None
    config: Optional[dict] = None

    @classmethod
    def from_snapshot(cls, data: dict) -> "VersionField":
        known = {k: v for k, v in data.items() if k in SNAPSHOT_FIELD_ATTRS}
        return cls(**known)


class PublishedForm:
    """A form as respondents and graders see it: the live form (name, status,
    audience, settings) with the structure of one published version. Reads
    like a Form, so the submission code takes either."""

    def __init__(self, form: Form, version: FormVersion):
        self._form = form
        self.version = version
        snapshot = version.snapshot or {}
        self.sections: Optional[list[dict]] = snapshot.get("sections")
        self.fields: list[VersionField] = sorted(
            (VersionField.from_snapshot(f) for f in snapshot.get("fields") or []),
            key=lambda f: (f.order, f.id),
        )

    @property
    def form(self) -> Form:
        return self._form

    @property
    def version_id(self) -> int:
        return self.version.id

    def __getattr__(self, name: str) -> Any:
        # only reached for what isn't set above: everything live on the form
        return getattr(self._form, name)
