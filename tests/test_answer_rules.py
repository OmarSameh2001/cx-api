import pytest
from fastapi import HTTPException

from modules.forms.model import Form, FormField
from modules.submissions import repository as subs_repo
from modules.submissions.answer_rules import validate_answer_values
from tests.conftest import employee_token, make_form, make_submission


def form_with(type_, options=None):
    return Form(fields=[FormField(id=1, question="Q", type=type_, options=options)])


@pytest.mark.parametrize(
    "type_, options, value",
    [
        ("single_choice", ["a", "b"], "a"),
        ("multi_choice", ["a", "b"], ["a", "b"]),
        ("multi_choice", ["a", "b"], "a, b"),
        ("boolean", None, "true"),
        ("boolean", None, False),
        ("scale", None, 5),
        ("text", None, "anything"),
        ("date", None, "2026-10-23"),
        ("email", None, "ann@acme.io"),
        ("phone_number", None, "+1 (555) 010-0100"),
        ("file", None, "report.pdf"),
        ("text", None, ""),  # empty is the required check's business
    ],
)
def test_accepts(type_, options, value):
    validate_answer_values(form_with(type_, options), {"1": value})


@pytest.mark.parametrize(
    "type_, options, value",
    [
        ("single_choice", ["a", "b"], "c"),
        ("multi_choice", ["a", "b"], ["a", "a"]),
        ("multi_choice", ["a", "b"], [{"x": 1}]),
        ("boolean", None, "maybe"),
        ("scale", None, 6),
        ("scale", None, True),
        ("text", None, {"nested": "object"}),
        ("text", None, "x" * 5001),
        ("date", None, "yesterday"),
        ("email", None, "not-an-email"),
        ("phone_number", None, "call me"),
        ("file", None, "x" * 300),
    ],
)
def test_rejects(type_, options, value):
    with pytest.raises(HTTPException) as e:
        validate_answer_values(form_with(type_, options), {"1": value})
    assert e.value.status_code == 422


def test_draft_mode_allows_half_typed_formats_but_not_oversize():
    validate_answer_values(form_with("email"), {"1": "ann@"}, draft=True)
    with pytest.raises(HTTPException):
        validate_answer_values(form_with("text"), {"1": "x" * 5001}, draft=True)


def test_draft_save_drops_unknown_keys(client, monkeypatch):
    sub = make_submission(make_form())
    monkeypatch.setattr(subs_repo, "get_submission", lambda db, sid: sub)
    monkeypatch.setattr(subs_repo, "save", lambda db, s: s)
    res = client.patch(
        "/submissions/500/draft",
        json={"answers": {"101": "A", "999": "junk"}},
        headers=employee_token(id=2),
    )
    assert res.status_code == 200
    assert sub.answers == {"101": "A"}
