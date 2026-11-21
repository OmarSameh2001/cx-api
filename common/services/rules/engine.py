"""The shared rule engine (E1.7): one JSON rule format, evaluated without eval.

A rule is JSON: a literal (null, true/false, a number, a string), a list of
rules (each one evaluated), or an operation, an object with exactly one key,
the operator, whose value holds its arguments: {"<": [{"var": "nps"}, 7]}.
A value that isn't a list is one argument: {"var": "nps"} is {"var": ["nps"]}.

The same format runs in the browser (cx-front/utils/rules/engine.ts). Both
evaluators must give the same result for every rule; cases.json, next to
this file, holds the examples both test suites run. rule.schema.json is the
format's JSON Schema and the list of operators, with what each one does.

Two kinds of failure:
- A malformed rule (unknown operator, wrong number of arguments, too deep or
  too big) raises RuleError, from validate() and from evaluate().
- A well-formed rule given unexpected data never raises: arithmetic on
  something that isn't a number gives null, a comparison between different
  types is false, a missing variable is null (or the default given).
"""

import math
import re
from datetime import date
from typing import Any, Callable, Optional

MAX_DEPTH = 32
MAX_NODES = 1000
# whole numbers up to this are written as integers (and are exact in JS)
_SAFE_INTEGER = 2**53 - 1
# ASCII digits only: Python's \d also matches Arabic-Indic digits, JS's doesn't
_ISO_DATE = re.compile(r"([0-9]{4})-([0-9]{2})-([0-9]{2})")
_INDEX = re.compile(r"0|[1-9][0-9]*")


class RuleError(ValueError):
    """The rule itself is malformed. `path` points at the bad part."""

    def __init__(self, message: str, path: str = "$"):
        super().__init__(f"{path}: {message}")
        self.path = path
        self.reason = message


# operator -> (min args, max args or None for no limit)
ARITY: dict[str, tuple[int, Optional[int]]] = {
    "var": (1, 2),
    "and": (1, None),
    "or": (1, None),
    "not": (1, 1),
    "if": (2, None),
    "==": (2, 2),
    "!=": (2, 2),
    "<": (2, 3),
    "<=": (2, 3),
    ">": (2, 2),
    ">=": (2, 2),
    "+": (1, None),
    "-": (1, 2),
    "*": (1, None),
    "/": (2, 2),
    "%": (2, 2),
    "abs": (1, 1),
    "round": (1, 2),
    "min": (1, None),
    "max": (1, None),
    "sum": (1, None),
    "avg": (1, None),
    "in": (2, 2),
    "any_of": (2, 2),
    "all_of": (2, 2),
    "length": (1, 1),
    "empty": (1, 1),
    "lower": (1, 1),
    "days_between": (2, 2),
}
OPERATORS = frozenset(ARITY)


# ── values ───────────────────────────────────────────────────────────────────

def _is_number(v: Any) -> bool:
    # bool is an int in Python; in a rule it never counts as a number
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def _number(x: float) -> Any:
    """A computed number as JSON would carry it: whole values as integers,
    so Python and JS print the same result. inf/nan can't be JSON: null."""
    if isinstance(x, float):
        if math.isnan(x) or math.isinf(x):
            return None
        if x.is_integer() and abs(x) <= _SAFE_INTEGER:
            return int(x)
    return x


def truthy(v: Any) -> bool:
    """false, null, 0, "" and [] are false; everything else is true."""
    if v is None or v is False:
        return False
    if _is_number(v):
        return v != 0
    if isinstance(v, (str, list)):
        return len(v) > 0
    return True


def equal(a: Any, b: Any) -> bool:
    """Strict, deep equality. Numbers compare by value (1 equals 1.0); no
    other conversions: "1" is not 1, and true is not 1."""
    if _is_number(a) and _is_number(b):
        return a == b
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if a is None or b is None:
        return a is None and b is None
    if isinstance(a, str) and isinstance(b, str):
        return a == b
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(equal(x, y) for x, y in zip(a, b))
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(equal(a[k], b[k]) for k in a)
    return False


def _compare(a: Any, b: Any) -> Optional[int]:
    """-1, 0 or 1 for two numbers or two strings (by code point); None
    when they can't be ordered."""
    if _is_number(a) and _is_number(b):
        return (a > b) - (a < b)
    if isinstance(a, str) and isinstance(b, str):
        return (a > b) - (a < b)
    return None


def _numbers(values: list[Any]) -> Optional[list[float]]:
    """Every value as a number, with lists spread out one level; None if
    anything isn't a number."""
    out: list[float] = []
    for v in values:
        items = v if isinstance(v, list) else [v]
        for item in items:
            if not _is_number(item):
                return None
            out.append(float(item))
    return out


def _lookup(data: Any, path: Any) -> tuple[bool, Any]:
    """(found, value) for a dotted path: "a.b.0" reads data["a"]["b"][0]."""
    if _is_number(path):
        path = str(_number(float(path)))
    if not isinstance(path, str):
        return False, None
    if path == "":
        return True, data
    current = data
    for part in path.split("."):
        if isinstance(current, dict):
            if part not in current:
                return False, None
            current = current[part]
        elif isinstance(current, list):
            if not _INDEX.fullmatch(part) or int(part) >= len(current):
                return False, None
            current = current[int(part)]
        else:
            return False, None
    return True, current


def _parse_date(v: Any) -> Optional[date]:
    if not isinstance(v, str):
        return None
    m = _ISO_DATE.match(v)
    if m is None:
        return None
    try:
        return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
    except ValueError:
        return None


def _as_list(v: Any) -> list[Any]:
    return v if isinstance(v, list) else [v]


def _contains(items: list[Any], value: Any) -> bool:
    return any(equal(item, value) for item in items)


# ── validation ───────────────────────────────────────────────────────────────

def _args(node: dict) -> tuple[str, list[Any]]:
    (op, raw), = node.items()
    return op, raw if isinstance(raw, list) else [raw]


def validate(rule: Any) -> None:
    """Raises RuleError if the rule is malformed; returns None otherwise."""
    nodes = 0

    def walk(node: Any, path: str, depth: int) -> None:
        nonlocal nodes
        nodes += 1
        if nodes > MAX_NODES:
            raise RuleError(f"rule has more than {MAX_NODES} parts", path)
        if depth > MAX_DEPTH:
            raise RuleError(f"rule is nested more than {MAX_DEPTH} levels deep", path)
        if node is None or isinstance(node, (bool, str)):
            return
        if _is_number(node):
            if isinstance(node, float) and not math.isfinite(node):
                raise RuleError("numbers must be finite", path)
            return
        if isinstance(node, list):
            for i, item in enumerate(node):
                walk(item, f"{path}[{i}]", depth + 1)
            return
        if not isinstance(node, dict):
            raise RuleError(f"unsupported value of type {type(node).__name__}", path)
        if len(node) != 1:
            raise RuleError("an operation must have exactly one operator", path)
        op, args = _args(node)
        if op not in ARITY:
            raise RuleError(f"unknown operator {op!r}", path)
        low, high = ARITY[op]
        if len(args) < low or (high is not None and len(args) > high):
            wanted = f"{low}" if low == high else f"{low} to {high}" if high else f"at least {low}"
            raise RuleError(f"{op!r} takes {wanted} argument(s), got {len(args)}", path)
        for i, arg in enumerate(args):
            walk(arg, f"{path}.{op}[{i}]", depth + 1)

    walk(rule, "$", 0)


# ── evaluation ───────────────────────────────────────────────────────────────

def _op_var(args, data, ev):
    found, value = _lookup(data, ev(args[0]))
    if (not found or value is None) and len(args) > 1:
        return ev(args[1])
    return value if found else None


def _op_if(args, data, ev):
    i = 0
    while i + 1 < len(args):
        if truthy(ev(args[i])):
            return ev(args[i + 1])
        i += 2
    return ev(args[i]) if i < len(args) else None


def _op_ordered(predicate: Callable[[int], bool]):
    def run(args, data, ev):
        values = [ev(a) for a in args]
        for a, b in zip(values, values[1:]):
            c = _compare(a, b)
            if c is None or not predicate(c):
                return False
        return True
    return run


def _arith(args, ev) -> Optional[list[float]]:
    values = [ev(a) for a in args]
    if not all(_is_number(v) for v in values):
        return None
    return [float(v) for v in values]


def _op_plus(args, data, ev):
    nums = _arith(args, ev)
    if nums is None:
        return None
    total = 0.0
    for n in nums:
        total += n
    return _number(total)


def _op_minus(args, data, ev):
    nums = _arith(args, ev)
    if nums is None:
        return None
    return _number(-nums[0] if len(nums) == 1 else nums[0] - nums[1])


def _op_times(args, data, ev):
    nums = _arith(args, ev)
    if nums is None:
        return None
    product = 1.0
    for n in nums:
        product *= n
    return _number(product)


def _op_divide(args, data, ev):
    nums = _arith(args, ev)
    if nums is None or nums[1] == 0:
        return None
    return _number(nums[0] / nums[1])


def _op_modulo(args, data, ev):
    nums = _arith(args, ev)
    if nums is None or nums[1] == 0:
        return None
    # the sign follows the dividend, as in JS
    return _number(math.fmod(nums[0], nums[1]))


def _op_abs(args, data, ev):
    v = ev(args[0])
    return _number(abs(float(v))) if _is_number(v) else None


def _op_round(args, data, ev):
    v = ev(args[0])
    digits = ev(args[1]) if len(args) > 1 else 0
    if not _is_number(v) or not _is_number(digits):
        return None
    if digits != int(digits) or not 0 <= digits <= 10:
        return None
    factor = 10.0 ** int(digits)
    # half away from zero, the same in Python and JS (not banker's rounding)
    magnitude = math.floor(abs(float(v)) * factor + 0.5) / factor
    return _number(-magnitude if v < 0 else magnitude)


def _op_reduce(kind: str):
    def run(args, data, ev):
        nums = _numbers([ev(a) for a in args])
        if nums is None:
            return None
        if not nums:
            return 0 if kind == "sum" else None
        if kind == "min":
            return _number(min(nums))
        if kind == "max":
            return _number(max(nums))
        total = 0.0
        for n in nums:
            total += n
        return _number(total if kind == "sum" else total / len(nums))
    return run


def _op_in(args, data, ev):
    needle, haystack = ev(args[0]), ev(args[1])
    if isinstance(haystack, str):
        return isinstance(needle, str) and needle in haystack
    if isinstance(haystack, list):
        return _contains(haystack, needle)
    return False


def _op_any_of(args, data, ev):
    value, options = ev(args[0]), ev(args[1])
    if not isinstance(options, list) or value is None:
        return False
    return any(_contains(options, v) for v in _as_list(value))


def _op_all_of(args, data, ev):
    value, required = ev(args[0]), ev(args[1])
    if not isinstance(required, list):
        return False
    chosen = [] if value is None else _as_list(value)
    return all(_contains(chosen, r) for r in required)


def _op_length(args, data, ev):
    v = ev(args[0])
    # strings count characters (code points), as the JS evaluator does
    return len(v) if isinstance(v, (str, list)) else None


def _op_empty(args, data, ev):
    v = ev(args[0])
    return v is None or v == "" or (isinstance(v, (list, dict)) and len(v) == 0)


def _op_lower(args, data, ev):
    v = ev(args[0])
    return v.lower() if isinstance(v, str) else None


def _op_days_between(args, data, ev):
    start, end = _parse_date(ev(args[0])), _parse_date(ev(args[1]))
    if start is None or end is None:
        return None
    return (end - start).days


_OPS: dict[str, Callable] = {
    "var": _op_var,
    "and": lambda args, data, ev: all(truthy(ev(a)) for a in args),
    "or": lambda args, data, ev: any(truthy(ev(a)) for a in args),
    "not": lambda args, data, ev: not truthy(ev(args[0])),
    "if": _op_if,
    "==": lambda args, data, ev: equal(ev(args[0]), ev(args[1])),
    "!=": lambda args, data, ev: not equal(ev(args[0]), ev(args[1])),
    "<": _op_ordered(lambda c: c < 0),
    "<=": _op_ordered(lambda c: c <= 0),
    ">": _op_ordered(lambda c: c > 0),
    ">=": _op_ordered(lambda c: c >= 0),
    "+": _op_plus,
    "-": _op_minus,
    "*": _op_times,
    "/": _op_divide,
    "%": _op_modulo,
    "abs": _op_abs,
    "round": _op_round,
    "min": _op_reduce("min"),
    "max": _op_reduce("max"),
    "sum": _op_reduce("sum"),
    "avg": _op_reduce("avg"),
    "in": _op_in,
    "any_of": _op_any_of,
    "all_of": _op_all_of,
    "length": _op_length,
    "empty": _op_empty,
    "lower": _op_lower,
    "days_between": _op_days_between,
}
assert _OPS.keys() == ARITY.keys()


def evaluate(rule: Any, data: Any = None) -> Any:
    """The rule's value for this data. Raises RuleError only if the rule is
    malformed (see validate)."""
    validate(rule)

    def ev(node: Any) -> Any:
        if isinstance(node, list):
            return [ev(item) for item in node]
        if not isinstance(node, dict):
            return node
        op, args = _args(node)
        return _OPS[op](args, data, ev)

    return ev(rule)
