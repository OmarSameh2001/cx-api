"""E1.7: the Python rule evaluator against the shared examples.

cases.json is the contract between the two evaluators: the TypeScript one in
cx-front runs the same file (e2e/rule-engine.spec.ts). A failure here means
Python and the browser could disagree on a rule.
"""

import json
import math

import pytest

from common.services.rules import (
    ARITY, CASES_PATH, MAX_DEPTH, MAX_NODES, OPERATORS, SCHEMA_PATH, RuleError, evaluate, validate,
)

CASES = json.loads(CASES_PATH.read_text(encoding="utf-8"))["cases"]
SCHEMA = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def same(actual, expected) -> bool:
    """JSON equality where 3 matches 3.0 but true never matches 1."""
    if isinstance(expected, bool) or isinstance(actual, bool):
        return type(actual) is type(expected) and actual == expected
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        return actual == expected
    if isinstance(expected, list):
        return isinstance(actual, list) and len(actual) == len(expected) and all(
            same(a, e) for a, e in zip(actual, expected)
        )
    if isinstance(expected, dict):
        return isinstance(actual, dict) and actual.keys() == expected.keys() and all(
            same(actual[k], expected[k]) for k in expected
        )
    return type(actual) is type(expected) and actual == expected


def test_case_names_are_unique():
    names = [c["name"] for c in CASES]
    assert len(names) == len(set(names))


def test_every_operator_has_a_case():
    used: set[str] = set()

    def collect(node):
        if isinstance(node, list):
            for item in node:
                collect(item)
        elif isinstance(node, dict):
            for op, args in node.items():
                used.add(op)
                collect(args)

    for case in CASES:
        if not case.get("error"):
            collect(case["rule"])
    assert OPERATORS - used == set()


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_shared_case(case):
    if case.get("error"):
        with pytest.raises(RuleError):
            evaluate(case["rule"], case.get("data"))
        with pytest.raises(RuleError):
            validate(case["rule"])
        return
    result = evaluate(case["rule"], case.get("data"))
    assert same(result, case["result"]), f"got {result!r}, wanted {case['result']!r}"


def test_schema_lists_exactly_the_engine_operators():
    operation = SCHEMA["$defs"]["operation"]
    assert set(operation["propertyNames"]["enum"]) == OPERATORS
    assert set(operation["properties"]) == OPERATORS
    for op, spec in operation["properties"].items():
        assert spec["description"], op
        assert tuple(spec["x-arity"]) == ARITY[op], op


def test_whole_results_are_integers():
    # so a result prints the same in Python and JS ("3", not "3.0")
    assert isinstance(evaluate({"*": [1.5, 2]}), int)
    assert isinstance(evaluate({"round": 2.5}), int)
    assert isinstance(evaluate({"/": [1, 4]}), float)


def test_never_runs_code():
    # strings are data, never evaluated
    assert evaluate("__import__('os').system('echo hi')") == "__import__('os').system('echo hi')"
    assert evaluate({"var": "__class__"}, {}) is None
    assert evaluate({"var": "__class__.__name__"}, {"a": 1}) is None


def test_node_limit():
    validate([1] * (MAX_NODES - 1))
    with pytest.raises(RuleError, match="more than"):
        validate([1] * MAX_NODES)


def test_depth_limit_matches_the_shared_cases():
    rule = True
    for _ in range(MAX_DEPTH):
        rule = {"not": rule}
    validate(rule)
    with pytest.raises(RuleError, match="nested"):
        validate({"not": rule})


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), {1, 2}, (1, 2), object()])
def test_non_json_values_are_rejected(bad):
    with pytest.raises(RuleError):
        validate({"==": [bad, 1]})


def test_error_points_at_the_bad_part():
    with pytest.raises(RuleError) as err:
        validate({"and": [True, {"or": [{"nope": 1}]}]})
    assert err.value.path == "$.and[1].or[0]"
    assert "nope" in err.value.reason


def test_infinite_data_is_not_a_number_result():
    assert evaluate({"+": [{"var": "x"}, 1]}, {"x": math.inf}) is None
