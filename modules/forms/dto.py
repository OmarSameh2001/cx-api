import re
from datetime import datetime
from typing import Annotated, Any, Literal, Optional, Union

from pydantic import (
    BaseModel, ConfigDict, Field, StringConstraints, ValidationError, field_validator, model_validator,
)

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
    # E2.1
    "long_text",
    "dropdown",
    "number",
    "nps",
    "rating",
    "likert",
    "choice_grid",
    "checkbox_grid",
    "currency",
    "slider",
    "image_choice",
    "time",
    # display blocks: shown to respondents, never answered
    "heading",
    "paragraph",
    "image",
    "video",
]
SubmitterType = Literal["employee", "customer"]
FormType = Literal["questionnaire", "exam"]

AUTO_GRADABLE_TYPES = {"single_choice", "multi_choice", "boolean", "dropdown"}
BRANCHABLE_TYPES = {"single_choice", "boolean", "dropdown"}
# questions answered by picking one or more of `options`
CHOICE_TYPES = {"single_choice", "multi_choice", "dropdown", "image_choice"}
# rows x columns, answered with {row: column} ({row: [columns]} for checkboxes)
GRID_TYPES = {"likert", "choice_grid", "checkbox_grid"}
# content between questions: no answer, no score, never required
DISPLAY_TYPES = {"heading", "paragraph", "image", "video"}
# a display block may have no title; a question always has one
UNTITLED_TYPES = {"image", "video"}
# form_fields.options is ARRAY(String(255))
MAX_OPTION_LENGTH = 255
MAX_OPTIONS = 200
MAX_GRID_ROWS = 50
MAX_GRID_COLUMNS = 10
MAX_LONG_TEXT_LENGTH = 20000
CURRENCIES = ("SAR", "EGP", "AED", "USD")

# A jump target: a section id, or "end" to finish the form.
SectionTarget = Union[int, Literal["end"]]


# --- question config (T1.4.1, E2.1) --------------------------------------------
# form_fields.config holds what a question type needs beyond its options. Each
# type has one schema; a key it doesn't declare is rejected. Respondents are
# served the config, so nothing secret (answer keys, scoring) belongs in it.
# Stored without its defaults; every read fills them in (config_with_defaults).


class MediaRef(BaseModel):
    """An image uploaded for the form (files purpose `form_media`). Readers
    get its link from the form's `media` map, keyed by file id."""
    model_config = ConfigDict(extra="forbid")
    file_id: int = Field(gt=0)
    alt: Optional[str] = Field(default=None, max_length=255)


Label = Optional[Annotated[str, StringConstraints(strip_whitespace=True, max_length=120)]]
GridLabel = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=MAX_OPTION_LENGTH)]


def _distinct(values: list[str], what: str) -> list[str]:
    if len(set(values)) != len(values):
        raise ValueError(f"{what} must be distinct")
    return values


class NoConfig(BaseModel):
    """Every question type's config: an optional image shown with the
    question (T2.1.14)."""
    model_config = ConfigDict(extra="forbid")
    image: Optional[MediaRef] = None


class FileQuestionConfig(LimitWrite):
    """Limits for this question's uploads. Like an organisation's limits they
    can only tighten size and types; image settings override. (`image` here
    is the upload's image policy, so the question's picture is `image_ref`.)"""
    model_config = ConfigDict(extra="forbid")
    image_ref: Optional[MediaRef] = None


class ChoiceConfig(NoConfig):
    # one image per option, by position; null where an option has none
    option_images: Optional[list[Optional[MediaRef]]] = Field(default=None, max_length=MAX_OPTIONS)


class ImageChoiceConfig(ChoiceConfig):
    # pick several pictures instead of one
    multiple: bool = False


class ScaleConfig(NoConfig):
    """A linear scale from `min` to `max`; the endpoint labels stay in
    `options` ([low label, high label]). Defaults: 1 to 5, as before."""
    min: Literal[0, 1] = 1
    max: int = Field(default=5, ge=3, le=10)
    # respondents may answer "na" instead of a point
    allow_na: bool = False


class NpsConfig(NoConfig):
    """0 to 10: 9–10 promoters, 7–8 passives, 0–6 detractors."""
    low_label: Label = None
    high_label: Label = None


class RatingConfig(NoConfig):
    levels: int = Field(default=5, ge=3, le=10)


class LongTextConfig(NoConfig):
    max_length: Optional[int] = Field(default=None, ge=1, le=MAX_LONG_TEXT_LENGTH)


class NumberConfig(NoConfig):
    min: Optional[float] = None
    max: Optional[float] = None
    integer_only: bool = False
    unit: Optional[Annotated[str, StringConstraints(strip_whitespace=True, max_length=16)]] = None

    @model_validator(mode="after")
    def _ordered(self):
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError("min must not be greater than max")
        return self


class CurrencyConfig(NoConfig):
    currency: Literal["SAR", "EGP", "AED", "USD"] = "USD"
    min: Optional[float] = Field(default=None, ge=0)
    max: Optional[float] = Field(default=None, ge=0)

    @model_validator(mode="after")
    def _ordered(self):
        if self.min is not None and self.max is not None and self.min > self.max:
            raise ValueError("min must not be greater than max")
        return self


MAX_SLIDER_STEPS = 1000


class SliderConfig(NoConfig):
    min: float = 0
    max: float = 100
    step: float = Field(default=1, gt=0)
    low_label: Label = None
    high_label: Label = None

    @model_validator(mode="after")
    def _fits(self):
        if self.min >= self.max:
            raise ValueError("min must be less than max")
        steps = (self.max - self.min) / self.step
        if steps > MAX_SLIDER_STEPS:
            raise ValueError(f"a slider has at most {MAX_SLIDER_STEPS} steps")
        if abs(steps - round(steps)) > 1e-9:
            raise ValueError("max - min must be a whole number of steps")
        return self


DEFAULT_LIKERT_COLUMNS = (
    "Strongly disagree", "Disagree", "Neutral", "Agree", "Strongly agree",
)


class GridConfig(NoConfig):
    """Statements (rows) answered on the same columns."""
    rows: list[GridLabel] = Field(min_length=1, max_length=MAX_GRID_ROWS)
    columns: list[GridLabel] = Field(min_length=2, max_length=MAX_GRID_COLUMNS)

    @field_validator("rows")
    @classmethod
    def _distinct_rows(cls, v):
        return _distinct(v, "rows")

    @field_validator("columns")
    @classmethod
    def _distinct_columns(cls, v):
        return _distinct(v, "columns")


class LikertConfig(GridConfig):
    """A grid whose columns are an ordered agreement scale, left to right."""
    columns: list[GridLabel] = Field(
        default_factory=lambda: list(DEFAULT_LIKERT_COLUMNS), min_length=2, max_length=MAX_GRID_COLUMNS
    )


class ParagraphConfig(BaseModel):
    """Heading and paragraph blocks: `question` is the title, `help_text` the body."""
    model_config = ConfigDict(extra="forbid")


class ImageBlockConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    image: MediaRef


# YouTube or Vimeo; the respondent view embeds the video from its id
_VIDEO_URL = re.compile(
    r"^https://(www\.)?(youtube\.com/watch\?v=[\w-]{6,20}([&#].*)?|youtu\.be/[\w-]{6,20}(\?.*)?"
    r"|youtube\.com/(embed|shorts)/[\w-]{6,20}(\?.*)?|(player\.)?vimeo\.com/(video/)?\d{4,12}(\?.*)?)$"
)


class VideoBlockConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")
    url: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)]

    @field_validator("url")
    @classmethod
    def _known_host(cls, v):
        if not _VIDEO_URL.match(v):
            raise ValueError("url must be a YouTube or Vimeo link")
        return v


QUESTION_CONFIG_SCHEMAS: dict[str, type[BaseModel]] = {
    "single_choice": ChoiceConfig,
    "multi_choice": ChoiceConfig,
    "boolean": NoConfig,
    "text": NoConfig,
    "date": NoConfig,
    "phone_number": NoConfig,
    "email": NoConfig,
    "file": FileQuestionConfig,
    "scale": ScaleConfig,
    "long_text": LongTextConfig,
    "dropdown": NoConfig,
    "number": NumberConfig,
    "nps": NpsConfig,
    "rating": RatingConfig,
    "likert": LikertConfig,
    "choice_grid": GridConfig,
    "checkbox_grid": GridConfig,
    "currency": CurrencyConfig,
    "slider": SliderConfig,
    "image_choice": ImageChoiceConfig,
    "time": NoConfig,
    "heading": ParagraphConfig,
    "paragraph": ParagraphConfig,
    "image": ImageBlockConfig,
    "video": VideoBlockConfig,
}


def _error_text(exc: ValidationError) -> str:
    return "; ".join(
        f"{'.'.join(str(p) for p in e['loc']) or 'config'}: {e['msg']}" for e in exc.errors()
    )


def _dumped(parsed: BaseModel, **kwargs) -> dict:
    data = parsed.model_dump(exclude_none=True, **kwargs)
    if "option_images" in data:
        # keep the positions: an option without an image is a null, not a gap
        data["option_images"] = [
            img.model_dump(exclude_none=True) if img else None
            for img in getattr(parsed, "option_images") or []
        ]
    return {k: v for k, v in data.items() if v != {}}


def validate_question_config(field_type: str, config: Optional[dict]) -> Optional[dict]:
    """The config as stored: validated, defaults and unset keys dropped, None
    when empty. Types whose config has required keys (grids, image and video
    blocks) are checked even when none is sent."""
    try:
        parsed = QUESTION_CONFIG_SCHEMAS[field_type].model_validate(config or {})
    except ValidationError as exc:
        raise ValueError(f"invalid config for a {field_type} question: {_error_text(exc)}") from None
    return _dumped(parsed, exclude_defaults=True) or None


def read_config(field_type: Any, config: Any) -> Optional[BaseModel]:
    """A stored config with its defaults, or None when it doesn't fit the
    type's schema (written by hand, or by an older version)."""
    schema = QUESTION_CONFIG_SCHEMAS.get(field_type)
    if schema is None or not isinstance(config, (dict, type(None))):
        return None
    try:
        return schema.model_validate(config or {})
    except ValidationError:
        return None


def config_with_defaults(field_type: Any, config: Any) -> Optional[dict]:
    """A stored config as editors get it: every key the type declares, with
    its default where unset. One that doesn't fit is served as stored."""
    parsed = read_config(field_type, config)
    if parsed is None:
        return config if isinstance(config, dict) else None
    return _dumped(parsed) or None


def respondent_config(field_type: Any, config: Any) -> Optional[dict]:
    """A stored config as respondents get it: only the keys the type's schema
    declares, with defaults, so nothing written around the schema (by hand, or
    by an older version) is served to them."""
    schema = QUESTION_CONFIG_SCHEMAS.get(field_type)
    if schema is None or not isinstance(config, (dict, type(None))):
        return None
    parsed = read_config(field_type, config)
    if parsed is not None:
        return _dumped(parsed) or None
    return {k: v for k, v in (config or {}).items() if k in schema.model_fields} or None


def _media_id(ref: Any) -> Optional[int]:
    if isinstance(ref, dict):
        file_id = ref.get("file_id")
        if isinstance(file_id, int) and not isinstance(file_id, bool) and file_id > 0:
            return file_id
    return None


def media_ids_in_config(config: Any) -> set[int]:
    """File ids of the form images a stored config names."""
    if not isinstance(config, dict):
        return set()
    refs = [config.get("image"), config.get("image_ref"), *(config.get("option_images") or [])]
    return {i for i in map(_media_id, refs) if i is not None}


# --- form settings (T1.4.2) --------------------------------------------------


HexColor = Annotated[str, StringConstraints(pattern=r"^#[0-9a-fA-F]{6}$")]


class FormTheme(BaseModel):
    """How the respondent view looks (T2.1.15)."""
    model_config = ConfigDict(extra="forbid")
    cover: Optional[MediaRef] = None
    background_image: Optional[MediaRef] = None
    # buttons, selections and the progress bar
    primary_color: Optional[HexColor] = None
    background_color: Optional[HexColor] = None


def media_ids_in_theme(theme: Any) -> set[int]:
    if not isinstance(theme, dict):
        return set()
    refs = [theme.get("cover"), theme.get("background_image")]
    return {i for i in map(_media_id, refs) if i is not None}


class FormSettings(BaseModel):
    """How a form behaves, stored in forms.settings. A new setting needs a
    default here and no migration: rows without it read the default."""
    model_config = ConfigDict(extra="forbid")
    # exams only: the attempt expires this long after it starts
    time_limit_minutes: Optional[int] = Field(default=None, ge=1)
    # None: unlimited
    max_attempts: Optional[int] = Field(default=None, ge=1)
    results_revealed: bool = False
    theme: Optional[FormTheme] = None


class FormSettingsRead(FormSettings):
    # serve what is stored, even a key this version no longer knows
    model_config = ConfigDict(extra="ignore")


class FormSettingsPatch(BaseModel):
    """FormUpdate's settings: keys sent replace the stored ones, the rest stay."""
    model_config = ConfigDict(extra="forbid")
    time_limit_minutes: Optional[int] = Field(default=None, ge=1)
    max_attempts: Optional[int] = Field(default=None, ge=1)
    results_revealed: bool = False
    theme: Optional[FormTheme] = None


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
    # a display block's title or text; image and video blocks may leave it empty
    question: str
    type: FieldType
    options: Optional[list[str]] = None
    right_answer: Optional[str] = None
    order: int = 0
    help_text: Optional[str] = None
    is_required: bool = False
    score_weight: float = 0.0
    section_id: Optional[int] = None
    # answer -> section to jump to; only for single_choice, dropdown and boolean
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
            raise ValueError("branching is only allowed on single_choice, dropdown and boolean fields")
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
        if type_ in CHOICE_TYPES:
            if not v or len(v) < 2:
                raise ValueError(f"{type_} fields require at least 2 options")
            if len(v) > MAX_OPTIONS:
                raise ValueError(f"a question has at most {MAX_OPTIONS} options")
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
        if type_ in ("single_choice", "dropdown"):
            if v not in options:
                raise ValueError(f"right_answer must be one of options for {type_}")
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

    @model_validator(mode="after")
    def _validate_type_rules(self):
        if not self.question and self.type not in UNTITLED_TYPES:
            raise ValueError("question must not be empty")
        if self.config is None and (self.id is None or "config" in self.model_fields_set):
            # a config that is needed (grid rows, a block's picture) can't be left out
            # (an existing field sent without one keeps what it has: see _field_rows)
            self.config = validate_question_config(self.type, None)
        if self.type in DISPLAY_TYPES:
            # nothing to answer: whatever came with the block is dropped
            self.options = None
            self.right_answer = None
            self.is_required = False
            self.score_weight = 0.0
            self.branching = None
        elif self.type in GRID_TYPES:
            self.options = None
        images = (self.config or {}).get("option_images")
        if images is not None and len(images) > len(self.options or []):
            raise ValueError("option_images can't have more entries than options")
        return self


class FormFieldRead(FormFieldBase):
    model_config = ConfigDict(from_attributes=True)
    id: int
    # stable across versions (see FormField.key); set by the server
    key: Optional[str] = None

    @field_validator("config")
    @classmethod
    def _with_defaults(cls, v, info):
        return config_with_defaults(info.data.get("type"), v)


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
    # links to the images the draft and the theme use, by file id (E2.1);
    # filled in by the controller. Links expire: reload the form for new ones.
    media: dict[str, str] = {}


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
    media: dict[str, str] = {}


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
