from datetime import datetime
from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator, model_validator

from modules.files.dto import LimitWrite


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
# form_fields.options is ARRAY(String(255))
MAX_OPTION_LENGTH = 255

# A jump target: a section id, or "end" to finish the form.
SectionTarget = Union[int, Literal["end"]]


# --- question config (T1.4.1) ------------------------------------------------
# form_fields.config holds what a question type needs beyond its options. Each
# type has one schema; a key it doesn't declare is rejected. Respondents are
# served the config, so nothing secret (answer keys, scoring) belongs in it.


class NoConfig(BaseModel):
    """For types with nothing to configure yet."""
    model_config = ConfigDict(extra="forbid")


class FileQuestionConfig(LimitWrite):
    """Limits for this question's uploads. Like an organisation's limits they
    can only tighten size and types; image settings override."""
    model_config = ConfigDict(extra="forbid")


QUESTION_CONFIG_SCHEMAS: dict[str, type[BaseModel]] = {
    "single_choice": NoConfig,
    "multi_choice": NoConfig,
    "boolean": NoConfig,
    "text": NoConfig,
    "date": NoConfig,
    "phone_number": NoConfig,
    "email": NoConfig,
    "file": FileQuestionConfig,
    "scale": NoConfig,
}


def _error_text(exc: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(p) for p in e['loc']) or 'config'}: {e['msg']}" for e in exc.errors()
    )


def validate_question_config(field_type: str, config: Optional[dict]) -> Optional[dict]:
    """The config as stored: validated, unset keys dropped, None when empty."""
    if not config:
        return None
    try:
        parsed = QUESTION_CONFIG_SCHEMAS[field_type].model_validate(config)
    except ValidationError as exc:
        raise ValueError(f"invalid config for a {field_type} question: {_error_text(exc)}") from None
    data = {k: v for k, v in parsed.model_dump(exclude_none=True).items() if v != {}}
    return data or None


def respondent_config(field_type: Any, config: Any) -> Optional[dict]:
    """A stored config as respondents get it: only the keys the type's schema
    declares, so nothing written around the schema (by hand, or by an older
    version) is served to them."""
    schema = QUESTION_CONFIG_SCHEMAS.get(field_type)
    if schema is None or not isinstance(config, dict):
        return None
    return {k: v for k, v in config.items() if k in schema.model_fields} or None


# --- form settings (T1.4.2) --------------------------------------------------


class FormSettings(BaseModel):
    """How a form behaves, stored in forms.settings. A new setting needs a
    default here and no migration: rows without it read the default."""
    model_config = ConfigDict(extra="forbid")
    # exams only: the attempt expires this long after it starts
    time_limit_minutes: Optional[int] = Field(default=None, ge=1)
    # None: unlimited
    max_attempts: Optional[int] = Field(default=None, ge=1)
    results_revealed: bool = False


class FormSettingsRead(FormSettings):
    # serve what is stored, even a key this version no longer knows
    model_config = ConfigDict(extra="ignore")


class FormSettingsPatch(BaseModel):
    """FormUpdate's settings: keys sent replace the stored ones, the rest stay."""
    model_config = ConfigDict(extra="forbid")
    time_limit_minutes: Optional[int] = Field(default=None, ge=1)
    max_attempts: Optional[int] = Field(default=None, ge=1)
    results_revealed: bool = False


# Before `settings`, these were top-level form attributes. They're still
# accepted there and still served there, until the frontend uses `settings`.
LEGACY_SETTING_KEYS = ("time_limit_minutes", "max_attempts", "results_revealed")


def _fold_legacy_settings(data: Any) -> Any:
    """Moves top-level legacy settings into `settings`; a key sent in both
    places takes the `settings` value."""
    if not isinstance(data, dict) or not any(k in data for k in LEGACY_SETTING_KEYS):
        return data
    data = dict(data)
    settings = data.get("settings")
    if settings is not None and not isinstance(settings, dict):
        return data  # let the settings field report the bad type
    settings = dict(settings or {})
    for key in LEGACY_SETTING_KEYS:
        if key not in data:
            continue
        value = data.pop(key)
        if key == "results_revealed" and value is None:
            continue  # null used to mean "leave it as it is"
        settings.setdefault(key, value)
    data["settings"] = settings
    return data


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
    # per-type settings; see QUESTION_CONFIG_SCHEMAS
    config: Optional[dict[str, Any]] = None


class FormFieldCreate(FormFieldBase):
    # on update: existing field id to edit in place; omit for a new field.
    # An existing field sent without `config` keeps the config it has.
    id: Optional[int] = None

    # The rules below run on writes only. FormFieldRead serves what is stored,
    # so a row that predates a rule (or was fixed by hand) can't break reads.

    @field_validator("config")
    @classmethod
    def _validate_config(cls, v, info):
        type_ = info.data.get("type")
        if type_ is None:
            # type already failed validation; that error is the useful one
            return v
        return validate_question_config(type_, v)

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
        too_long = [o for o in v or [] if len(o) > MAX_OPTION_LENGTH]
        if too_long:
            raise ValueError(
                f"options must be at most {MAX_OPTION_LENGTH} characters, got one of {len(too_long[0])}"
            )
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
    # stable across versions (see FormField.key); set by the server
    key: Optional[str] = None


class FormBase(BaseModel):
    name: str = Field(min_length=1, max_length=255)
    source_type: Optional[str] = None
    type: FormType = "questionnaire"
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
    settings: FormSettings = Field(default_factory=FormSettings)
    fields: list[FormFieldCreate] = Field(min_length=1)
    sections: Optional[list[FormSectionPayload]] = None
    # Deprecated: legacy input, folded into `settings`. Also served as copies
    # of settings, because the AI generator returns this payload to the builder.
    time_limit_minutes: Optional[int] = None
    max_attempts: Optional[int] = None
    results_revealed: bool = False

    _fold_legacy = model_validator(mode="before")(_fold_legacy_settings)

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
            if self.settings.max_attempts is None:
                self.settings.max_attempts = 1
        for key in LEGACY_SETTING_KEYS:
            setattr(self, key, getattr(self.settings, key))
        return self


class FormUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=255)
    source_type: Optional[str] = None
    type: Optional[FormType] = None
    description: Optional[str] = None
    submitter_type: Optional[list[SubmitterType]] = None
    assigned_to_units: Optional[list[int]] = None
    # top-level time_limit_minutes, max_attempts and results_revealed are
    # still accepted and land here
    settings: Optional[FormSettingsPatch] = None
    is_active: Optional[bool] = None
    is_archived: Optional[bool] = None
    fields: Optional[list[FormFieldCreate]] = None
    sections: Optional[list[FormSectionPayload]] = None

    _fold_legacy = model_validator(mode="before")(_fold_legacy_settings)

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


class FormVersionRef(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    number: int
    published_at: datetime
    published_by: Optional[int] = None


class FormRead(FormBase):
    """The form as its editors see it: `fields` and `sections` are the draft.
    Respondents get `current_version` until the draft is published."""
    model_config = ConfigDict(from_attributes=True)
    id: int
    settings: FormSettingsRead = Field(default_factory=FormSettingsRead)
    # Deprecated copies of settings.*, until the frontend reads `settings`
    time_limit_minutes: Optional[int] = None
    max_attempts: Optional[int] = None
    results_revealed: bool = False
    is_active: bool
    is_archived: bool
    public_token: Optional[str] = None
    created_at: datetime
    created_by: Optional[int]
    fields: list[FormFieldRead] = []
    sections: Optional[list[dict]] = None
    # a response has been submitted (drafts don't count). Filled in by the
    # controller. Edits no longer lock: they go into the next version.
    has_submissions: bool = False
    current_version: Optional[FormVersionRef] = None
    # the draft differs from current_version (or nothing is published yet);
    # filled in by the controller
    has_unpublished_changes: bool = False


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
    current_version_id: Optional[int] = None


MyStatus = Literal["not_started", "in_progress", "submitted", "late", "expired"]


class AssignedFormSummary(FormSummary):
    my_status: MyStatus = "not_started"
    attempts_used: int = 0


# --- versions (E1.5) ---------------------------------------------------------


class FormVersionSummary(FormVersionRef):
    question_count: int = 0
    # finalized responses to this version
    submission_count: int = 0


class FormVersionRead(FormVersionRef):
    type: str
    sections: Optional[list[dict]] = None
    fields: list[FormFieldRead] = []


class DiffItem(BaseModel):
    # questions: their key; sections: their id
    ref: Union[str, int]
    label: str
    # attribute names that differ; values are in the two versions
    changes: list[str] = []


class DiffPart(BaseModel):
    added: list[DiffItem] = []
    removed: list[DiffItem] = []
    changed: list[DiffItem] = []


class FormVersionDiff(BaseModel):
    # None: the empty form before version 1
    from_number: Optional[int]
    # a version number, or "draft"
    to: Union[int, Literal["draft"]]
    questions: DiffPart
    sections: DiffPart

    @property
    def is_empty(self) -> bool:
        return not any(
            getattr(part, kind) for part in (self.questions, self.sections)
            for kind in ("added", "removed", "changed")
        )
