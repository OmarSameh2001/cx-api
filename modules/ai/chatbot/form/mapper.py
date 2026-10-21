"""GeneratedForm -> FormCreate, the payload the form builder submits.

Things a model commonly gets slightly wrong and that have one obvious fix
(a boolean answered "Yes", a backward jump, grading on a questionnaire) are
repaired here the same way the builder cleans a form before saving. Anything
else is left to FormCreate's validators, whose errors go back to the model.
"""

from typing import Optional

from fastapi import HTTPException

from modules.forms.dto import BRANCHABLE_TYPES, FormCreate
from modules.forms.service import validate_branching

from .dto import FormGenerateRequest
from .schema import GeneratedField, GeneratedForm, SectionRef


class FormMappingError(ValueError):
    pass


_TRUE = {"true", "yes", "y"}
_FALSE = {"false", "no", "n"}
DEFAULT_SECTION_WEIGHT = 1.0


def _boolean_key(value: str) -> Optional[str]:
    v = value.strip().lower()
    if v in _TRUE:
        return "true"
    if v in _FALSE:
        return "false"
    return None


def _options(f: GeneratedField) -> Optional[list[str]]:
    if f.type in ("single_choice", "multi_choice"):
        return list(dict.fromkeys(o.strip() for o in f.options or [] if o.strip()))
    if f.type == "scale":
        labels = [o.strip() for o in f.options or []]
        return (labels + ["", ""])[:2]
    if f.type == "boolean":
        return ["Yes", "No"]
    return None


def _right_answer(type_: str, options: Optional[list[str]], value: Optional[str]) -> Optional[str]:
    """Mirror of the builder's validRightAnswer: keep the answer only where
    the backend accepts it for this type and these options."""
    if not value or not value.strip():
        return None
    opts = options or []
    if type_ == "single_choice":
        return value.strip() if value.strip() in opts else None
    if type_ == "multi_choice":
        kept = list(dict.fromkeys(p.strip() for p in value.split(",") if p.strip() in opts))
        return ",".join(kept) or None
    if type_ == "boolean":
        return _boolean_key(value)
    if type_ == "text":
        return value.strip()
    return None


def _target(ref: Optional[SectionRef], source_id: int, section_count: int) -> Optional[SectionRef]:
    # section ids are their 1-based position, so forward means a bigger id;
    # backward or unknown jumps are dropped like the builder does
    if ref == "end":
        return "end"
    if isinstance(ref, int) and source_id < ref <= section_count:
        return ref
    return None


def _branching(
    f: GeneratedField, options: Optional[list[str]], section_id: int, section_count: int
) -> Optional[dict[str, SectionRef]]:
    rules: dict[str, SectionRef] = {}
    for rule in f.branching or []:
        key = _boolean_key(rule.answer) if f.type == "boolean" else rule.answer.strip()
        if key is None or (f.type != "boolean" and key not in (options or [])):
            continue
        target = _target(rule.go_to, section_id, section_count)
        if target is not None:
            rules[key] = target
    return rules or None


def _field(
    f: GeneratedField,
    *,
    order: int,
    section_id: Optional[int],
    section_count: int,
    is_exam: bool,
    can_branch: bool,
) -> dict:
    options = _options(f)
    # only gradable types (choice, boolean, text) can come back with an answer
    right_answer = _right_answer(f.type, options, f.right_answer) if is_exam else None
    graded = right_answer is not None
    branching = None
    if can_branch and section_id is not None and f.type in BRANCHABLE_TYPES:
        branching = _branching(f, options, section_id, section_count)
    return {
        "question": f.question.strip(),
        "type": f.type,
        "options": options,
        "right_answer": right_answer,
        "order": order,
        "help_text": (f.help_text or "").strip() or None,
        # a timed exam auto-submits blanks, so its questions are never required
        "is_required": False if is_exam else f.is_required,
        "score_weight": (f.score_weight or 1.0) if graded else 0.0,
        "section_id": section_id,
        "branching": branching,
    }


def to_form_create(generated: GeneratedForm, request: FormGenerateRequest) -> FormCreate:
    form_type = request.type or generated.type
    is_exam = form_type == "exam"

    groups = [(s.fields, s) for s in generated.sections]
    if groups and generated.fields:
        # the model filled both; keep its loose questions in the first section
        groups[0] = (generated.fields + groups[0][0], groups[0][1])
    if not groups:
        groups = [(generated.fields, None)]
    section_count = len(generated.sections)

    sections: list[dict] = []
    fields: list[dict] = []
    for index, (group_fields, section) in enumerate(groups):
        section_id = index + 1 if section else None
        if section:
            sections.append({
                "id": section_id,
                "title": section.title.strip(),
                "description": (section.description or "").strip() or None,
                "order": index,
                "score_weight": section.score_weight if is_exam else DEFAULT_SECTION_WEIGHT,
                "next_section_id": None if is_exam else _target(
                    section.next_section, section_id, section_count
                ),
            })
        has_branch = False
        for f in group_fields:
            field = _field(
                f,
                order=len(fields),
                section_id=section_id,
                section_count=section_count,
                is_exam=is_exam,
                # questionnaires only, one branching question per section
                can_branch=not is_exam and not has_branch,
            )
            has_branch = has_branch or field["branching"] is not None
            fields.append(field)

    form = FormCreate.model_validate({
        "name": generated.name.strip(),
        "description": (generated.description or "").strip() or None,
        "type": form_type,
        "submitter_type": request.submitter_type or generated.submitter_type,
        # unit ids belong to the organisation; the user picks them in the builder
        "assigned_to_units": None,
        "time_limit_minutes": generated.time_limit_minutes if is_exam else None,
        "max_attempts": generated.max_attempts,
        "results_revealed": generated.results_revealed,
        "fields": fields,
        "sections": sections or None,
    })
    try:
        validate_branching(
            form.type,
            [s.model_dump() for s in form.sections] if form.sections else None,
            [f.model_dump() for f in form.fields],
        )
    except HTTPException as e:
        raise FormMappingError(str(e.detail)) from e
    return form
