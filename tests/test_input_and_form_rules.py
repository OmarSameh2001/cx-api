"""Input validation (bad values are 4xx, never 5xx) and form business rules."""

import pytest

from modules.forms import repository as forms_repo
from modules.submissions import repository as subs_repo
from tests.conftest import employee_token, make_form, make_submission

# ── input validation: bad values are 4xx, never 5xx ─────────────────────────

ADMIN = dict(is_admin=True, permissions=["forms:read", "forms:create", "submissions:read", "units:read",
                                          "employees:read", "employees:create"])


@pytest.mark.parametrize("method, path, body", [
    ("GET", "/forms/not-a-number", None),
    ("GET", "/forms/-1", None),
    ("GET", "/forms?limit=0", None),
    ("GET", "/forms?limit=100000", None),
    ("GET", "/forms?offset=-5", None),
    ("GET", "/keywords?tenant_id=not-a-uuid", None),
    ("POST", "/forms", {}),
    ("POST", "/forms", {"name": "x", "submitter_type": [], "fields": []}),
    ("POST", "/forms", {"name": "x", "submitter_type": ["robot"], "fields": [{"question": "Q", "type": "text"}]}),
    ("POST", "/forms", {"name": "x", "submitter_type": ["employee"], "fields": [{"question": "Q", "type": "hologram"}]}),
    ("POST", "/forms", {"name": "x" * 300, "submitter_type": ["employee"], "fields": [{"question": "Q", "type": "text"}]}),
    ("POST", "/employees", {"first_name": "a", "last_name": "b", "username": "c", "email": "not-an-email", "password": "secret1"}),
    ("POST", "/employees", {"first_name": "a", "last_name": "b", "username": "c", "email": "a@b.co", "password": "1"}),
    ("POST", "/public/forms/tok/submit", {"customer": {"email": "a@b.co", "first_name": "A", "last_name": "B"}, "answers": "not-a-dict"}),
    ("POST", "/public/forms/tok/submit", {"customer": {"email": "a@b.co", "first_name": "", "last_name": "B"}, "answers": {}}),
])
def test_bad_input_is_a_client_error(client, monkeypatch, method, path, body):
    monkeypatch.setattr(subs_repo, "list_submissions", lambda db, **kw: [])
    monkeypatch.setattr(subs_repo, "count_submissions", lambda db, **kw: 0)
    monkeypatch.setattr(forms_repo, "get_form", lambda db, fid: None)
    monkeypatch.setattr(forms_repo, "get_form_by_token", lambda db, t: None)
    res = client.request(method, path, headers=employee_token(**ADMIN), **({"json": body} if body is not None else {}))
    assert 400 <= res.status_code < 500, f"{res.status_code}: {res.text[:120]}"


# ── form business rules ─────────────────────────────────────────────────────

@pytest.fixture
def questionnaire(monkeypatch):
    form = make_form(type="questionnaire", created_by=1, max_attempts=1, is_active=True)
    monkeypatch.setattr(forms_repo, "get_form", lambda db, fid: form if fid == form.id else None)
    monkeypatch.setattr(forms_repo, "get_form_by_token", lambda db, t: form if t == "tok" else None)
    monkeypatch.setattr(forms_repo, "form_has_submissions", lambda db, fid: True)
    return form


PUBLIC = {"customer": {"email": "ann@acme.io", "first_name": "Ann", "last_name": "Lee"}, "answers": {"101": "A"}}


def test_public_link_refuses_an_archived_form(client, questionnaire):
    questionnaire.is_archived = True
    assert client.post("/public/forms/tok/submit", json=PUBLIC).status_code == 409


def test_public_link_refuses_an_inactive_form(client, questionnaire):
    questionnaire.is_active = False
    assert client.get("/public/forms/tok").status_code == 409


def test_public_link_refuses_an_exam(client, questionnaire):
    questionnaire.type = "exam"
    assert client.get("/public/forms/tok").status_code == 403


def test_public_link_refuses_an_employee_only_form(client, questionnaire):
    questionnaire.submitter_type = ["employee"]
    assert client.get("/public/forms/tok").status_code == 403


def test_public_attempt_limit_is_enforced(client, db, questionnaire, monkeypatch):
    from modules.customers import repository as customers_repo
    from modules.customers.model import Customer

    monkeypatch.setattr(customers_repo, "get_by_email", lambda db, **kw: Customer(id=5, organisation_id=10, email="ann@acme.io", first_name="Ann", last_name="Lee"))
    monkeypatch.setattr(subs_repo, "count_finalized_attempts", lambda db, **kw: 1)
    res = client.post("/public/forms/tok/submit", json=PUBLIC)
    assert res.status_code == 409 and db.commits == 0


def test_submitted_answers_cannot_be_edited_as_a_draft(client, db, questionnaire, monkeypatch):
    sub = make_submission(questionnaire, user_id=2, status="submitted")
    monkeypatch.setattr(subs_repo, "get_submission", lambda db, sid: sub)
    res = client.patch(f"/submissions/{sub.id}/draft", headers=employee_token(id=2), json={"answers": {"101": "B"}})
    assert res.status_code == 409 and db.commits == 0


def test_form_structure_is_locked_once_it_has_responses(client, db, questionnaire):
    questionnaire.is_active = False
    res = client.patch(f"/forms/{questionnaire.id}", headers=employee_token(id=1), json={
        "fields": [{"question": "brand new", "type": "text"}],
    })
    assert res.status_code == 409 and db.commits == 0


def test_form_with_responses_cannot_be_deleted(client, db, questionnaire):
    questionnaire.is_active = False
    assert client.delete(f"/forms/{questionnaire.id}", headers=employee_token(id=1)).status_code == 409


def test_active_form_cannot_be_edited(client, db, questionnaire):
    assert client.patch(f"/forms/{questionnaire.id}", headers=employee_token(id=1), json={"name": "x"}).status_code == 409


def test_respondent_cannot_start_a_second_attempt_beyond_the_limit(client, db, questionnaire, monkeypatch):
    questionnaire.submitter_type = ["employee"]
    monkeypatch.setattr(subs_repo, "count_finalized_attempts", lambda db, **kw: 1)
    monkeypatch.setattr(subs_repo, "find_open_submission", lambda db, **kw: None)
    monkeypatch.setattr(subs_repo, "find_in_progress", lambda db, **kw: None, raising=False)
    res = client.post("/submissions/start", headers=employee_token(id=2), json={"form_id": questionnaire.id})
    assert res.status_code == 409, f"{res.status_code}: {res.text[:120]}"
