"""Reviewing submissions follows the same rule as the frontend's buttons:
creator, admin, or submissions:read (old spelling submissions:view)."""

import pytest

from modules.forms import repository as forms_repo
from modules.submissions import repository as subs_repo
from tests.conftest import employee_token, make_form, make_submission


@pytest.fixture
def listing(monkeypatch):
    form = make_form()
    calls = []
    monkeypatch.setattr(forms_repo, "get_form", lambda db, fid: form)
    monkeypatch.setattr(subs_repo, "list_submissions", lambda db, **kw: calls.append(kw) or [])
    monkeypatch.setattr(subs_repo, "count_submissions", lambda db, **kw: 0)
    return calls


@pytest.mark.parametrize(
    "who, sees_everyone",
    [
        (dict(id=1), True),  # creator
        (dict(id=9, is_admin=True), True),
        (dict(id=9, permissions=["submissions:read"]), True),
        (dict(id=9, permissions=["submissions:view"]), True),
        (dict(id=9, permissions=["forms:read"]), False),
        (dict(id=9), False),
    ],
)
def test_who_lists_all_submissions_of_a_form(client, listing, who, sees_everyone):
    res = client.get("/submissions?form_id=7", headers=employee_token(**who))
    assert res.status_code == 200
    user_filter = listing[0]["user_id"]
    assert (user_filter is None) is sees_everyone
    if not sees_everyone:
        assert user_filter == who["id"]  # only their own


@pytest.mark.parametrize(
    "who, allowed",
    [
        (dict(id=9, is_admin=True), True),
        (dict(id=9, permissions=["submissions:read"]), True),
        (dict(id=9, permissions=["forms:read"]), False),
    ],
)
def test_who_can_reveal_a_result(client, monkeypatch, who, allowed):
    sub = make_submission(make_form(), status="submitted")
    monkeypatch.setattr(subs_repo, "get_submission", lambda db, sid: sub)
    monkeypatch.setattr(subs_repo, "save", lambda db, s: s)
    res = client.post("/submissions/500/reveal", headers=employee_token(**who))
    assert (res.status_code == 200) is allowed
    assert sub.results_revealed is allowed
