"""The shared rule format and its Python evaluator (E1.7). See engine.py."""

from pathlib import Path

from .engine import ARITY, MAX_DEPTH, MAX_NODES, OPERATORS, RuleError, equal, evaluate, truthy, validate

HERE = Path(__file__).resolve().parent
# the rule format's JSON Schema, which also lists and describes every operator
SCHEMA_PATH = HERE / "rule.schema.json"
# examples both evaluators (this one and cx-front/utils/rules) must pass
CASES_PATH = HERE / "cases.json"

__all__ = [
    "ARITY", "CASES_PATH", "MAX_DEPTH", "MAX_NODES", "OPERATORS", "RuleError", "SCHEMA_PATH",
    "equal", "evaluate", "truthy", "validate",
]
