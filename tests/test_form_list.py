"""GET /forms lists only forms the caller can open: everything in the org
for form readers/managers/reviewers, otherwise just their own."""

import pytest

from modules.forms import repository as forms_repo
from tests.conftest import employee_token


@pytest.fixture
def listing(monkeypatch):
    calls = []
    monkeypatch.setattr(forms_repo, "list_forms", lambda db, **kw: calls.append(kw) or [])
    monkeypatch.setattr(forms_repo, "count_forms", lambda db, **kw: calls.append(kw) or 0)
    return calls


@pytest.mark.parametrize(
    "who",
    [
        dict(is_admin=True),
        dict(permissions=["forms:read"]),
        dict(permissions=["forms:update"]),
        dict(permissions=["submissions:read"]),
        dict(permissions=["forms:manage"]),
    ],
)
def test_readers_list_the_whole_organisation(client, listing, who):
    res = client.get("/forms", headers=employee_token(id=9, **who))
    assert res.status_code == 200
    assert all(c["created_by"] is None and c["organisation_id"] == 10 for c in listing)


def test_readers_can_still_filter_by_creator(client, listing):
    client.get("/forms?created_by=4", headers=employee_token(id=9, permissions=["forms:read"]))
    assert all(c["created_by"] == 4 for c in listing)


def test_plain_employee_lists_only_their_own_forms(client, listing):
    res = client.get("/forms", headers=employee_token(id=9))
    assert res.status_code == 200
    assert listing and all(c["created_by"] == 9 for c in listing)


def test_plain_employee_asking_for_someone_elses_forms_gets_nothing(client, listing):
    res = client.get("/forms?created_by=4", headers=employee_token(id=9))
    assert res.status_code == 200
    assert res.json()["items"] == [] and res.json()["total"] == 0
    assert listing == []  # not even queried


def test_customers_cannot_list_forms(client, listing):
    from tests.conftest import customer_token

    assert client.get("/forms", headers=customer_token()).status_code == 403
