"""Blocker 4: deleting a form with responses is a clear 409, not a 500."""

import pytest
from sqlalchemy.exc import IntegrityError

from modules.forms import repository as forms_repo
from tests.conftest import FakeSession, employee_token, make_form


@pytest.fixture
def inactive_form(monkeypatch):
    form = make_form(is_active=False)
    monkeypatch.setattr(forms_repo, "get_form", lambda db, fid: form)
    return form


def test_form_with_responses_returns_409(client, monkeypatch, inactive_form):
    monkeypatch.setattr(forms_repo, "form_has_submissions", lambda db, fid: True)
    deleted = []
    monkeypatch.setattr(forms_repo, "delete_form", lambda db, f: deleted.append(f) or True)

    res = client.delete("/forms/7", headers=employee_token(id=1))
    assert res.status_code == 409
    assert res.json()["error"] == "form_has_submissions"
    assert "Archive" in res.json()["detail"]
    assert deleted == []


def test_form_with_only_drafts_is_deleted(client, monkeypatch, inactive_form):
    monkeypatch.setattr(forms_repo, "form_has_submissions", lambda db, fid: False)
    deleted = []
    monkeypatch.setattr(forms_repo, "delete_form", lambda db, f: deleted.append(f) or True)

    res = client.delete("/forms/7", headers=employee_token(id=1))
    assert res.status_code == 204
    assert deleted == [inactive_form]


def test_response_arriving_mid_delete_still_returns_409(client, monkeypatch, inactive_form):
    monkeypatch.setattr(forms_repo, "form_has_submissions", lambda db, fid: False)
    monkeypatch.setattr(forms_repo, "delete_form", lambda db, f: False)

    res = client.delete("/forms/7", headers=employee_token(id=1))
    assert res.status_code == 409
    assert res.json()["error"] == "form_has_submissions"


class _ForeignKeyViolation(FakeSession):
    def execute(self, *_a, **_k):
        return None  # the drafts delete

    def commit(self):
        raise IntegrityError("DELETE", {}, Exception("violates foreign key constraint"))


def test_repository_turns_foreign_key_violation_into_false():
    db = _ForeignKeyViolation()
    assert forms_repo.delete_form(db, make_form()) is False
    assert db.rollbacks == 1
