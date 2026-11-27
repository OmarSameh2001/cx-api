"""Form logic (E2.3): which questions a respondent is shown, and which
sections their path goes through, decided by rules in the shared format
(common/services/rules).

The browser runs the same logic (cx-front/utils/form/logic.ts) to show,
hide and page; the API runs this one to check what it is sent. Both must
agree: logic_cases.json, next to this file, holds the examples both test
suites run.

Rules read their data through `var`:
  {"var": "q.<key>"}          an earlier question's answer (by field key),
                              cleaned up per type: see answer_value
  {"var": "q.<key>.<row>"}    a grid row's answer, rows counted from 0
  {"var": "hidden.<name>"}    a value from the signed prefilled link

A question is shown when it is on the path (its section was visited, or it
has no section) and its `visible_if` rule holds (no rule: always). A hidden
question's answer reads as null, for every rule. A section's `routes` are
tried in order after it: the first whose `when` holds says where to go
(a later section, or "end"); none does: `next_section_id`, else the next
section. Old forms keep `branching` on a question ({answer: target});
section_routes reads it as routes.

Rules may only read earlier questions (by section, then order); the forms
service checks that on save, which also rules out loops. Evaluation doesn't
depend on the order questions are shown in (shuffling moves them).
"""

import math
import re
from dataclasses import dataclass, field as dataclass_field
from typing import Any, Iterable, Optional

from common.errors import AppError
from common.services.rules import RuleError, evaluate, truthy, validate

from .dto import DISPLAY_TYPES, GRID_TYPES

# what a rule may read: an answer (optionally a grid row) or a hidden value
_KEY = r"[A-Za-z0-9_-]{1,32}"
_ANSWER_REF = re.compile(rf"q\.({_KEY})(?:\.(0|[1-9][0-9]{{0,2}}))?")
_HIDDEN_REF = re.compile(r"hidden\.([a-z][a-z0-9_]{0,39})")
# the number answers may be written as, the same in Python and JS
_NUMBER = re.compile(r"[+-]?([0-9]+\.?[0-9]*|\.[0-9]+)([eE][+-]?[0-9]+)?")
_BLANKS = " \t\n\r"
MAX_ROUTES = 50

NUMBER_TYPES = {"number", "currency", "slider", "scale", "nps", "rating"}
TEXT_TYPES = {"text", "long_text", "email", "phone_number", "date", "time", "single_choice", "dropdown"}
NOT_APPLICABLE = "na"


# --- answers as rules read them --------------------------------------------------


def _empty(v: Any) -> bool:
    return v is None or v == "" or v == [] or v == {}


def _as_number(v: Any) -> Any:
    if isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return v if math.isfinite(v) else None
    if isinstance(v, str):
        text = v.strip(_BLANKS)
        if _NUMBER.fullmatch(text):
            number = float(text)
            return number if math.isfinite(number) else None
    return None


def _grid_rows(field: Any) -> list[str]:
    rows = (getattr(field, "config", None) or {}).get("rows")
    return [r for r in rows if isinstance(r, str)] if isinstance(rows, list) else []


def answer_value(field: Any, raw: Any) -> Any:
    """An answer as rules see it: null when unanswered; choices and text as
    strings, several choices as a list; yes/no as true or false; numbers,
    scales and ratings as numbers ("na" for a scale's N/A); a grid as
    {row index: column(s)}; a file as true."""
    type_ = field.type
    if type_ in DISPLAY_TYPES or _empty(raw):
        return None
    if type_ in TEXT_TYPES:
        return raw if isinstance(raw, str) else None
    if type_ in ("multi_choice", "image_choice"):
        if isinstance(raw, str):
            return raw if type_ == "image_choice" else [raw]
        if isinstance(raw, list):
            chosen = [v for v in raw if isinstance(v, str)]
            return chosen or None
        return None
    if type_ == "boolean":
        if isinstance(raw, bool):
            return raw
        if isinstance(raw, str) and raw.strip(_BLANKS).lower() in ("true", "false"):
            return raw.strip(_BLANKS).lower() == "true"
        return None
    if type_ in NUMBER_TYPES:
        if type_ == "scale" and raw == NOT_APPLICABLE:
            return NOT_APPLICABLE
        return _as_number(raw)
    if type_ in GRID_TYPES:
        if not isinstance(raw, dict):
            return None
        out = {}
        for i, row in enumerate(_grid_rows(field)):
            value = raw.get(row)
            if isinstance(value, str) and value != "":
                out[str(i)] = value
            elif isinstance(value, list):
                columns = [v for v in value if isinstance(v, str)]
                if columns:
                    out[str(i)] = columns
        return out or None
    if type_ == "file":
        return True if isinstance(raw, dict) and raw.get("file_id") is not None else None
    return raw if isinstance(raw, (str, bool, int, float)) else None


# --- what rules refer to ----------------------------------------------------------


@dataclass(frozen=True)
class Ref:
    kind: str  # "q" or "hidden"
    name: str  # the field key or the hidden field's name
    row: Optional[int] = None


class DynamicReference(ValueError):
    """A `var` whose path is computed, so what it reads can't be checked."""


def references(rule: Any) -> list[Ref]:
    """What a rule reads, in the order written. Raises DynamicReference for
    a path that isn't written out, and ValueError for one that reads
    anything but an answer or a hidden value."""
    found: list[Ref] = []

    def walk(node: Any) -> None:
        if isinstance(node, list):
            for item in node:
                walk(item)
            return
        if not isinstance(node, dict) or len(node) != 1:
            return
        (op, args), = node.items()
        args = args if isinstance(args, list) else [args]
        if op == "var":
            path = args[0] if args else None
            if not isinstance(path, str):
                raise DynamicReference(str(path))
            found.append(parse_ref(path))
            for extra in args[1:]:
                walk(extra)
            return
        for arg in args:
            walk(arg)

    walk(rule)
    return found


def parse_ref(path: str) -> Ref:
    m = _ANSWER_REF.fullmatch(path)
    if m:
        return Ref("q", m.group(1), int(m.group(2)) if m.group(2) is not None else None)
    m = _HIDDEN_REF.fullmatch(path)
    if m:
        return Ref("hidden", m.group(1))
    raise ValueError(path)


# --- routes ---------------------------------------------------------------------------


def ordered_sections(sections: Iterable[dict]) -> list[dict]:
    """Canonical section order: by `order`, then id."""
    return sorted(sections or [], key=lambda s: (s.get("order", 0) or 0, s["id"]))


def _legacy_literal(field_type: str, key: Any) -> tuple[bool, Any]:
    text = str(key).strip()
    if field_type == "boolean":
        lowered = text.lower()
        if lowered not in ("true", "false"):
            return False, None
        return True, lowered == "true"
    return True, text


def legacy_routes(section_id: int, fields: Iterable[Any]) -> list[dict]:
    """A section's old `branching` (on its first branching question, by order
    then id) as routes."""
    branching_fields = sorted(
        (f for f in fields if f.section_id == section_id and f.branching and getattr(f, "key", None)),
        key=lambda f: (f.order or 0, f.id or 0),
    )
    if not branching_fields:
        return []
    f = branching_fields[0]
    routes = []
    for answer, target in f.branching.items():
        ok, literal = _legacy_literal(f.type, answer)
        if ok:
            routes.append({"when": {"==": [{"var": f"q.{f.key}"}, literal]}, "to": target})
    return routes


def section_routes(section: dict, fields: Iterable[Any]) -> list[dict]:
    """The routes tried after a section: its own, or its old branching."""
    routes = section.get("routes")
    if isinstance(routes, list):
        return routes
    return legacy_routes(section["id"], fields)


def has_routing(sections: Optional[list[dict]], fields: Iterable[Any]) -> bool:
    fields = list(fields)
    return any(
        section_routes(s, fields) or s.get("next_section_id") is not None for s in sections or []
    )


# --- the path -------------------------------------------------------------------------


@dataclass
class Path:
    """Where a respondent's answers lead."""
    # sections visited, in order; None when the form has no sections
    sections: Optional[list[int]]
    # ids of the fields shown (questions and display blocks)
    shown: set[int] = dataclass_field(default_factory=set)

    @property
    def visited(self) -> Optional[set[int]]:
        return None if self.sections is None else set(self.sections)

    @property
    def last_section_id(self) -> Optional[int]:
        return self.sections[-1] if self.sections else None

    def is_shown(self, field: Any) -> bool:
        return field.id in self.shown


def _safe_truthy(rule: Any, data: dict, *, broken: bool) -> bool:
    try:
        return truthy(evaluate(rule, data))
    except RuleError:
        # a stored rule is checked on save; one that isn't valid shows the
        # question rather than lose it, and never routes
        return broken


def walk(form: Any, answers: Optional[dict[str, Any]], hidden: Optional[dict[str, Any]] = None) -> Path:
    """The respondent's path through `form` (a Form, a PublishedForm or
    anything with `sections` and `fields`) for these answers and hidden
    values."""
    answers = answers or {}
    hidden_values = {k: v for k, v in (hidden or {}).items() if isinstance(k, str)}
    fields = list(form.fields)
    sections = ordered_sections(form.sections or [])
    position = {s["id"]: i for i, s in enumerate(sections)}
    by_key = {f.key: f for f in fields if getattr(f, "key", None)}
    visited: set[int] = set()
    memo: dict[int, bool] = {}
    stack: set[int] = set()

    def section_pos(f: Any) -> int:
        if not sections:
            return 0
        return position.get(f.section_id, -1)

    def on_path(f: Any) -> bool:
        if not sections or f.section_id not in position:
            return True
        return f.section_id in visited

    def shown(f: Any) -> bool:
        if not on_path(f):
            return False
        if f.id in memo:
            return memo[f.id]
        if f.id in stack:
            return False
        rule = getattr(f, "visible_if", None)
        if rule is None:
            result = True
        else:
            stack.add(f.id)
            result = _safe_truthy(rule, data_for(rule, section_pos(f)), broken=True)
            stack.discard(f.id)
        memo[f.id] = result
        return result

    def value(key: str, horizon: int) -> Any:
        f = by_key.get(key)
        if f is None or f.type in DISPLAY_TYPES or section_pos(f) > horizon:
            return None
        if not shown(f):
            return None
        return answer_value(f, answers.get(str(f.id)))

    def data_for(rule: Any, horizon: int) -> dict:
        q: dict[str, Any] = {}
        try:
            refs = references(rule)
        except ValueError:
            refs = []
        for ref in refs:
            if ref.kind == "q" and ref.name not in q:
                q[ref.name] = value(ref.name, horizon)
        return {"q": q, "hidden": hidden_values}

    if not sections:
        ids = {f.id for f in sorted(fields, key=_rank) if shown(f)}
        return Path(sections=None, shown=ids)

    path: list[int] = []
    i = 0
    # every step either ends the walk or moves strictly forward
    while i < len(sections):
        section = sections[i]
        visited.add(section["id"])
        path.append(section["id"])
        target = None
        for route in section_routes(section, fields):
            if not isinstance(route, dict):
                continue
            if _safe_truthy(route.get("when"), data_for(route.get("when"), i), broken=False):
                target = route.get("to")
                break
        if target is None:
            target = section.get("next_section_id")
        if target == "end":
            break
        # a number naming a later section (true is not 1 here, as in JS)
        if (isinstance(target, (int, float)) and not isinstance(target, bool)
                and target in position and position[target] > i):
            i = position[target]
        else:
            i += 1

    ids = {f.id for f in sorted(fields, key=lambda f: (section_pos(f), *_rank(f))) if shown(f)}
    return Path(sections=path, shown=ids)


def _rank(f: Any) -> tuple:
    return (f.order or 0, f.id or 0)


def not_shown_ids(form: Any, path: Optional[Path]) -> set[str]:
    """Answer keys of the fields the path doesn't show."""
    if path is None:
        return set()
    return {str(f.id) for f in form.fields if f.id not in path.shown}


def hidden_refs(form: Any) -> set[str]:
    """The hidden values the form's rules read: all a respondent is sent."""
    names: set[str] = set()
    rules = [getattr(f, "visible_if", None) for f in form.fields]
    rules += [r.get("when") for s in form.sections or [] for r in (s.get("routes") or []) if isinstance(r, dict)]
    for rule in rules:
        if rule is None:
            continue
        try:
            names |= {r.name for r in references(rule) if r.kind == "hidden"}
        except ValueError:
            continue
    return names


def for_respondent(read: Any, form: Any, hidden: Optional[dict[str, Any]]) -> Any:
    """A respondent view (RespondentForm / PublicForm) with what the browser
    needs to run the logic: each section's routes (old branching read as
    routes) and the hidden values the rules read, no others."""
    by_id = {s["id"]: s for s in form.sections or []}
    sections = [
        s.model_copy(update={"routes": section_routes(by_id[s.id], form.fields) if s.id in by_id else []})
        for s in read.sections or []
    ] if read.sections is not None else None
    wanted = hidden_refs(form)
    values = {k: v for k, v in (hidden or {}).items() if k in wanted}
    return read.model_copy(update={"sections": sections, "hidden": values})


# --- checks on save -------------------------------------------------------------------


def _fail(code: str, **params) -> None:
    raise AppError(422, code, **params)


def _label(f: dict) -> str:
    return (f.get("question") or "").strip()[:80] or str(f.get("key"))


def check_rule(rule: Any, *, where: str, readable: dict[str, dict], hidden_keys: set[str]) -> None:
    """A rule is well formed and reads only what `readable` (key -> field
    row) and the declared hidden values hold."""
    try:
        validate(rule)
    except RuleError as exc:
        _fail("forms.rule_invalid", where=where, problem=exc.reason)
    try:
        refs = references(rule)
    except DynamicReference:
        _fail("forms.rule_dynamic_reference", where=where)
    except ValueError as exc:
        _fail("forms.rule_unknown_reference", where=where, ref=str(exc))
    for ref in refs:
        if ref.kind == "hidden":
            if ref.name not in hidden_keys:
                _fail("forms.rule_unknown_hidden", where=where, name=ref.name)
            continue
        target = readable.get(ref.name)
        if target is None:
            _fail("forms.rule_reads_later_question", where=where, key=ref.name)
        if ref.row is not None and target.get("type") not in GRID_TYPES:
            _fail("forms.rule_unknown_reference", where=where, ref=f"q.{ref.name}.{ref.row}")


def validate_logic(
    form_type: str,
    sections: Optional[list[dict]],
    fields: list[dict],
    hidden_keys: Iterable[str] = (),
) -> None:
    """Show/hide rules and section routes (field and section rows as saved).
    Rules read only earlier questions, routes go only forward, and both are
    for questionnaires."""
    sections = sections or []
    hidden_keys = set(hidden_keys)
    with_rules = [f for f in fields if f.get("visible_if") is not None]
    routed = [s for s in sections if s.get("routes")]
    if not with_rules and not routed:
        return
    if form_type == "exam":
        _fail("forms.branching_questionnaires_only" if routed else "forms.logic_questionnaires_only")

    keys = [f.get("key") for f in fields if f.get("key")]
    if len(keys) != len(set(keys)):
        _fail("forms.duplicate_field_keys")

    ordered = ordered_sections(sections)
    position = {s["id"]: i for i, s in enumerate(ordered)}

    def section_pos(f: dict) -> int:
        if not sections:
            return 0
        return position.get(f.get("section_id"), -1)

    ranked = sorted(
        enumerate(fields), key=lambda p: (section_pos(p[1]), p[1].get("order") or 0, p[0])
    )
    answerable = lambda f: f.get("key") and f.get("type") not in DISPLAY_TYPES  # noqa: E731

    earlier: dict[str, dict] = {}
    for _, f in ranked:
        if f.get("visible_if") is not None:
            check_rule(f["visible_if"], where=_label(f), readable=earlier, hidden_keys=hidden_keys)
        if answerable(f):
            earlier[f["key"]] = f

    for s in routed:
        if len(s["routes"]) > MAX_ROUTES:
            _fail("forms.too_many_routes", section=s.get("title") or s["id"], max=MAX_ROUTES)
        here = position[s["id"]]
        readable = {
            f["key"]: f for _, f in ranked if answerable(f) and section_pos(f) <= here
        }
        for route in s["routes"]:
            check_rule(route.get("when"), where=s.get("title") or str(s["id"]),
                       readable=readable, hidden_keys=hidden_keys)
            target = route.get("to")
            if target == "end":
                continue
            if target not in position:
                _fail("forms.branching_unknown_target", target=target)
            if position[target] <= here:
                _fail("forms.branching_backwards", source=s["id"], target=target)


def rewrite_keys(rule: Any, renamed: dict[str, str]) -> Any:
    """`rule` reading each renamed key under its new name."""
    if not renamed or rule is None:
        return rule
    if isinstance(rule, list):
        return [rewrite_keys(item, renamed) for item in rule]
    if not isinstance(rule, dict) or len(rule) != 1:
        return rule
    (op, args), = rule.items()
    if op == "var":
        items = args if isinstance(args, list) else [args]
        path = items[0] if items else None
        if isinstance(path, str):
            try:
                ref = parse_ref(path)
            except ValueError:
                ref = None
            if ref is not None and ref.kind == "q" and ref.name in renamed:
                new_path = f"q.{renamed[ref.name]}" + (f".{ref.row}" if ref.row is not None else "")
                items = [new_path, *items[1:]]
                return {"var": items if isinstance(args, list) else items[0]}
        return rule
    return {op: rewrite_keys(args, renamed)}
