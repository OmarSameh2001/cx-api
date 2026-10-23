"""Blockers 1 and 2: correct answers must not reach respondents, and form
reads are scoped to the caller's organisation."""

import pytest

from modules.forms import repository as forms_repo
from modules.submissions import repository as subs_repo
from tests.conftest import (
    customer_token,
    employee_token,
    make_form,
    make_submission,
)


@pytest.fixture
def form(monkeypatch):
    form = make_form()
    monkeypatch.setattr(forms_repo, "get_form", lambda db, fid: form if fid == form.id else None)
    monkeypatch.setattr(forms_repo, "form_has_submissions", lambda db, fid: False)
    return form


def right_answers(body):
    return [f["right_answer"] for f in body["fields"]]


# ── GET /forms/{id} ──────────────────────────────────────────────────────────

def test_creator_sees_correct_answers(client, form):
    res = client.get("/forms/7", headers=employee_token(id=1))
    assert res.status_code == 200
    assert right_answers(res.json()) == ["A", "Because of physics"]


@pytest.mark.parametrize(
    "who",
    [
        dict(is_admin=True),
        dict(permissions=["forms:update"]),
        dict(permissions=["submissions:read"]),
        dict(permissions=["forms:manage"]),  # legacy spelling
    ],
)
def test_managers_and_reviewers_see_correct_answers(client, form, who):
    res = client.get("/forms/7", headers=employee_token(id=9, **who))
    assert res.status_code == 200
    assert right_answers(res.json()) == ["A", "Because of physics"]


def test_forms_read_sees_questions_but_not_answers(client, form):
    res = client.get("/forms/7", headers=employee_token(id=9, permissions=["forms:read"]))
    assert res.status_code == 200
    body = res.json()
    assert [f["question"] for f in body["fields"]] == ["Pick A", "Explain"]
    assert right_answers(body) == [None, None]


def test_exam_taker_cannot_read_the_form(client, form):
    # a plain employee (the respondent) has no business reading the form
    res = client.get("/forms/7", headers=employee_token(id=2))
    assert res.status_code == 403
    assert "right_answer" not in res.text


def test_other_organisation_gets_404(client, form):
    res = client.get("/forms/7", headers=employee_token(id=1, organisation_id=99, is_admin=True))
    assert res.status_code == 404


def test_customer_token_cannot_read_any_form(client, form):
    res = client.get("/forms/7", headers=customer_token())
    assert res.status_code == 403
    assert "right_answer" not in res.text


# ── GET /submissions/{id}/form (the respondent view) ────────────────────────

@pytest.fixture
def stub_submission(monkeypatch, form):
    def install(**overrides):
        sub = make_submission(form, **overrides)
        monkeypatch.setattr(subs_repo, "get_submission", lambda db, sid: sub if sid == sub.id else None)
        monkeypatch.setattr(subs_repo, "save", lambda db, s: s)
        return sub
    return install


def test_respondent_gets_questions_without_answers(client, stub_submission):
    stub_submission()
    res = client.get("/submissions/500/form", headers=employee_token(id=2))
    assert res.status_code == 200
    body = res.json()
    assert [f["question"] for f in body["fields"]] == ["Pick A", "Explain"]
    assert body["time_limit_minutes"] == 30 and body["max_attempts"] == 1
    # nothing that grades or identifies the form's internals
    for leaked in ("right_answer", "score_weight", "public_token", "created_by", "Because of physics"):
        assert leaked not in res.text
    assert set(body["sections"][0]) == {"id", "title", "description", "order", "next_section_id"}


def test_respondent_view_is_owner_only(client, stub_submission):
    stub_submission()
    res = client.get("/submissions/500/form", headers=employee_token(id=3))
    assert res.status_code == 403


def test_respondent_view_closes_once_submitted(client, stub_submission):
    stub_submission(status="submitted")
    res = client.get("/submissions/500/form", headers=employee_token(id=2))
    assert res.status_code == 409
