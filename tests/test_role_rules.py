"""Role rules on the routes that check access themselves (forms, submissions,
organisations, AI), as plain unit tests on the existing harness.

Each test states the behaviour a default role *should* get, so a failure is
a finding. "agent" = the default agent role's permissions; "manager" likewise.
"""

import pytest

from modules.forms import repository as forms_repo
from modules.roles.permissions import DEFAULT_ROLES
from modules.submissions import repository as subs_repo
from tests.conftest import employee_token, make_form, make_submission

PERMS = {name: sorted(f"{r}:{a}" for r, a in keys) for name, _, keys in DEFAULT_ROLES if keys}
ADMIN_ID, AGENT_ID, OTHER_ID = 1, 5, 6


def agent():
    return employee_token(id=AGENT_ID, organisation_id=10, permissions=PERMS["agent"])


def manager():
    return employee_token(id=7, organisation_id=10, permissions=PERMS["manager"])


@pytest.fixture
def exam(monkeypatch):
    """An exam in org 10 created by the admin, inactive so it could be edited."""
    form = make_form(created_by=ADMIN_ID, is_active=False)
    monkeypatch.setattr(forms_repo, "get_form", lambda db, fid: form if fid == form.id else None)
    monkeypatch.setattr(forms_repo, "form_has_submissions", lambda db, fid: False)
    return form


# ── forms ───────────────────────────────────────────────────────────────────

def test_agent_cannot_create_forms(client, db, monkeypatch):
    monkeypatch.setattr(forms_repo, "create_form", lambda db, **kw: make_form(created_by=AGENT_ID))
    monkeypatch.setattr(forms_repo, "form_has_submissions", lambda db, fid: False)
    res = client.post("/forms", headers=agent(), json={
        "name": "f", "type": "questionnaire", "submitter_type": ["employee"],
        "fields": [{"question": "Q", "type": "text"}],
    })
    assert res.status_code == 403, f"agent (no forms:create) created a form: {res.status_code}"


def test_agent_does_not_see_exam_answers(client, exam):
    res = client.get(f"/forms/{exam.id}", headers=agent())
    assert res.status_code in (200, 403)
    if res.status_code == 200:
        answers = [f["right_answer"] for f in res.json()["fields"]]
        assert answers == [None, None], f"agent sees correct answers: {answers}"


@pytest.mark.parametrize("action", ["activate", "deactivate", "public-token", "duplicate", "reveal-results"])
def test_agent_cannot_manage_someone_elses_form(client, db, exam, monkeypatch, action):
    monkeypatch.setattr(forms_repo, "set_public_token", lambda db, f, t: f, raising=False)
    res = client.post(f"/forms/{exam.id}/{action}", headers=agent())
    assert res.status_code in (403, 404), f"{action} → {res.status_code}"


def test_agent_cannot_edit_or_delete_someone_elses_form(client, db, exam):
    assert client.patch(f"/forms/{exam.id}", headers=agent(), json={"name": "x"}).status_code in (403, 404)
    assert client.delete(f"/forms/{exam.id}", headers=agent()).status_code in (403, 404)


# ── submissions ─────────────────────────────────────────────────────────────

def test_agent_cannot_read_a_colleagues_submission(client, exam, monkeypatch):
    sub = make_submission(exam, user_id=OTHER_ID, status="submitted", score=0.9)
    sub.employee = None
    sub.customer = None
    monkeypatch.setattr(subs_repo, "get_submission", lambda db, sid: sub)
    res = client.get(f"/submissions/{sub.id}/detail", headers=agent())
    assert res.status_code in (403, 404), f"agent read a colleague's exam submission: {res.status_code}"


def test_agent_lists_only_their_own_submissions(client, exam, monkeypatch):
    seen = {}
    monkeypatch.setattr(subs_repo, "list_submissions", lambda db, **kw: seen.update(kw) or [])
    monkeypatch.setattr(subs_repo, "count_submissions", lambda db, **kw: 0)
    client.get(f"/submissions?form_id={exam.id}", headers=agent())
    assert seen.get("user_id") == AGENT_ID, f"agent's list is not limited to them: user_id={seen.get('user_id')}"


def test_agent_cannot_reveal_results(client, db, exam, monkeypatch):
    sub = make_submission(exam, user_id=OTHER_ID, status="submitted")
    monkeypatch.setattr(subs_repo, "get_submission", lambda db, sid: sub)
    monkeypatch.setattr(subs_repo, "save", lambda db, s: s, raising=False)
    res = client.post(f"/submissions/{sub.id}/reveal", headers=agent())
    assert res.status_code in (403, 404), f"agent revealed a result: {res.status_code}"


# ── organisation and AI ─────────────────────────────────────────────────────

def test_agent_cannot_edit_the_organisation(client, db, monkeypatch):
    from types import SimpleNamespace

    from modules.organisations import repository as orgs_repo

    monkeypatch.setattr(orgs_repo, "get_organisation", lambda db, oid: SimpleNamespace(id=oid, name="Acme"))
    assert client.patch("/organisations/10", headers=agent(), json={"name": "x"}).status_code == 403


def test_agent_cannot_generate_forms_with_ai(client, monkeypatch):
    from modules.ai.chatbot.form import controller as ai_controller

    called = []

    async def fake_generate(**kw):
        called.append(kw)
        return {}

    monkeypatch.setattr(ai_controller, "generate_form", fake_generate)
    res = client.post("/ai/forms/generate", headers=agent(), json={"prompt": "a survey"})
    assert res.status_code == 403 and called == []


# ── manager, for contrast: holds forms:create/update and submissions:read ──

def test_manager_can_create_forms(client, db, monkeypatch):
    monkeypatch.setattr(forms_repo, "create_form", lambda db, **kw: make_form(created_by=7))
    monkeypatch.setattr(forms_repo, "form_has_submissions", lambda db, fid: False)
    res = client.post("/forms", headers=manager(), json={
        "name": "f", "type": "questionnaire", "submitter_type": ["employee"],
        "fields": [{"question": "Q", "type": "text"}],
    })
    assert res.status_code == 201
