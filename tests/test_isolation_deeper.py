"""Isolation cases the end-to-end spec doesn't reach, as unit tests."""

from types import SimpleNamespace

from modules.forms import repository as forms_repo
from modules.shared.lookup import route as lookup_route
from modules.submissions import repository as subs_repo
from modules.units import repository as units_repo
from tests.conftest import employee_token, make_form, make_submission


def test_org_wide_reviewer_listing_is_still_limited_to_their_organisation(client, monkeypatch):
    seen = {}
    monkeypatch.setattr(subs_repo, "list_submissions", lambda db, **kw: seen.update(kw) or [])
    monkeypatch.setattr(subs_repo, "count_submissions", lambda db, **kw: 0)
    client.get("/submissions", headers=employee_token(organisation_id=10, is_admin=True))
    assert seen.get("organisation_id") == 10


def test_reviewer_cannot_open_a_submission_on_another_organisations_form(client, monkeypatch):
    other = make_form(organisation_id=20, created_by=99)
    sub = make_submission(other, user_id=98, status="submitted")
    monkeypatch.setattr(subs_repo, "get_submission", lambda db, sid: sub)
    for path in (f"/submissions/{sub.id}", f"/submissions/{sub.id}/detail", f"/submissions/{sub.id}/form"):
        res = client.get(path, headers=employee_token(organisation_id=10, is_admin=True))
        assert res.status_code in (403, 404), f"{path} → {res.status_code}"


def test_employee_lookup_is_limited_to_the_callers_units(client, monkeypatch):
    seen = {}
    monkeypatch.setattr(lookup_route, "search_employees", lambda db, **kw: seen.update(kw) or [])
    client.get("/lookups/employees", headers=employee_token(organisation_id=10, assigned_unit_ids=[3]))
    assert seen.get("parent_unit_ids") == [3]


def test_unit_lookup_is_limited_to_the_callers_organisation(client, monkeypatch):
    seen = {}
    monkeypatch.setattr(lookup_route, "search_units", lambda db, **kw: seen.update(kw) or [])
    client.get("/lookups/units", headers=employee_token(organisation_id=10, is_admin=True))
    assert seen.get("organisation_id") == 10


def test_admin_cannot_move_own_employee_into_another_organisations_unit(client, db, monkeypatch):
    from modules.employees import repository as employees_repo

    me = SimpleNamespace(id=4, organisation_id=10, unit_id=1, email="e@x.co", username="e", external_id=None)
    monkeypatch.setattr(employees_repo, "get_employee", lambda db, eid: me if eid == 4 else None)
    monkeypatch.setattr(units_repo, "get_unit", lambda db, uid: SimpleNamespace(id=uid, organisation_id=20))
    res = client.patch("/employees/4", json={"unit_id": 2},
                       headers=employee_token(organisation_id=10, is_admin=True, permissions=["employees:update"],
                                              assigned_unit_ids=[1]))
    assert res.status_code in (403, 404) and db.commits == 0


def test_duplicating_a_form_keeps_it_in_the_callers_organisation(client, db, monkeypatch):
    form = make_form(organisation_id=10, created_by=1)
    monkeypatch.setattr(forms_repo, "get_form", lambda db, fid: form)
    captured = {}
    monkeypatch.setattr(forms_repo, "create_form", lambda db, data, fields, created_by: captured.update(data) or form)
    monkeypatch.setattr(forms_repo, "form_has_submissions", lambda db, fid: False)
    client.post(f"/forms/{form.id}/duplicate", headers=employee_token(id=1, organisation_id=10, permissions=["forms:update"]))
    assert captured.get("organisation_id", 10) == 10
