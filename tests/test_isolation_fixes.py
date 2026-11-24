"""T0.6.1 findings, fixed: units, assignments, the parked tenant-scoped
modules (now unmounted), employee links, form unit targeting and the forms lookup all stay inside the
caller's organisation. (The end-to-end version against the real database is
cx-front/e2e/isolation.spec.ts.)"""

import uuid
from types import SimpleNamespace

import pytest

from modules.assignments import repository as assignments_repo
from modules.employees import repository as employees_repo
from modules.units import repository as units_repo
from tests.conftest import employee_token

OWN, OTHER = 10, 20
TENANT_OTHER = uuid.uuid4()
EVERYTHING = [
    f"{r}:{a}"
    for r in ["units", "assignments", "employees", "forms"]
    for a in ["read", "create", "update", "delete"]
]


def caller(**kw):
    return employee_token(organisation_id=OWN, permissions=EVERYTHING, assigned_unit_ids=[1], **kw)


UNITS = {1: SimpleNamespace(id=1, organisation_id=OWN), 2: SimpleNamespace(id=2, organisation_id=OTHER)}


@pytest.fixture(autouse=True)
def world(monkeypatch):
    monkeypatch.setattr(units_repo, "get_unit", lambda db, uid: UNITS.get(uid))
    monkeypatch.setattr(
        units_repo, "unit_ids_in_organisation",
        lambda db, ids, org: {i for i in ids if i in UNITS and UNITS[i].organisation_id == org},
    )


# ── units: the organisation comes from the token ────────────────────────────

@pytest.mark.parametrize("method, path, body", [
    ("GET", f"/units?organisation_id={OTHER}", None),
    ("GET", f"/units/2?organisation_id={OTHER}", None),
    ("PATCH", f"/units/2?organisation_id={OTHER}", {"name": "x"}),
    ("DELETE", f"/units/2?organisation_id={OTHER}", None),
    ("POST", "/units", {"name": "x", "organisation_id": OTHER}),
])
def test_naming_another_organisation_is_not_found(client, db, method, path, body):
    res = client.request(method, path, headers=caller(), **({"json": body} if body else {}))
    assert res.status_code == 404
    assert db.commits == 0


def test_another_organisations_unit_is_not_found_in_own_organisation(client):
    assert client.get("/units/2", headers=caller()).status_code == 404


def test_platform_admin_may_name_another_organisation(client, monkeypatch):
    seen = {}
    monkeypatch.setattr(units_repo, "list_units", lambda db, organisation_id, **kw: seen.setdefault("org", organisation_id) and [])
    monkeypatch.setattr(units_repo, "count_units", lambda db, organisation_id: 0)
    res = client.get(f"/units?organisation_id={OTHER}", headers=caller(is_platform_admin=True))
    assert res.status_code == 200 and seen["org"] == OTHER


# ── assignments ─────────────────────────────────────────────────────────────

def test_assignments_need_their_permissions(client):
    assert client.get("/assignments", headers=employee_token(organisation_id=OWN)).status_code == 403


def test_assignment_lists_are_scoped(client, monkeypatch):
    seen = {}
    monkeypatch.setattr(assignments_repo, "list_assignments", lambda db, **kw: seen.update(kw) or [])
    monkeypatch.setattr(assignments_repo, "count_assignments", lambda db, **kw: 0)
    assert client.get("/assignments", headers=caller()).status_code == 200
    assert seen["organisation_id"] == OWN


def test_another_organisations_assignment_is_not_found(client, db, monkeypatch):
    other = SimpleNamespace(id=5, unit=UNITS[2])
    monkeypatch.setattr(assignments_repo, "get_assignment", lambda db, aid: other)
    for method in ("GET", "PATCH", "DELETE"):
        kw = {"json": {"description": "x"}} if method == "PATCH" else {}
        assert client.request(method, "/assignments/5", headers=caller(), **kw).status_code == 404
    assert db.commits == 0


def test_cannot_assign_onto_another_organisations_unit(client, db, monkeypatch):
    monkeypatch.setattr(db, "get", lambda model, oid: {1: SimpleNamespace(organisation_id=OWN)}.get(oid) if model.__name__ == "Employee" else UNITS.get(oid), raising=False)
    res = client.post("/assignments", json={"user_id": 1, "unit_id": 2}, headers=caller())
    assert res.status_code == 404


# ── parked tenant-scoped modules: unmounted ──────────────────────────────────

@pytest.mark.parametrize("path", [
    "/tenants", "/keywords", "/mentions", "/platform-configs",
    "/notification-rules", "/notification-deliveries",
    "/mention-notification-rules", "/mention-notification-deliveries",
])
def test_parked_mentions_routers_are_not_mounted(client, path):
    res = client.get(f"{path}?tenant_id={TENANT_OTHER}", headers=caller(is_platform_admin=True))
    assert res.status_code == 404, path


# ── employees and forms can't point at another organisation ─────────────────

@pytest.fixture
def no_conflicts(monkeypatch):
    for name in ("get_employee_by_email", "get_employee_by_username", "get_employee_by_external_id"):
        monkeypatch.setattr(employees_repo, name, lambda db, v: None)
    monkeypatch.setattr(employees_repo, "get_employee",
                        lambda db, eid: SimpleNamespace(id=eid, organisation_id=OTHER))


@pytest.mark.parametrize("link", [{"manager_id": 99}, {"assigned_units": [2]}])
def test_employee_links_must_be_in_own_organisation(client, db, no_conflicts, link):
    res = client.post("/employees", headers=caller(), json={
        "first_name": "E", "last_name": "V", "username": "eve", "email": "eve@example.com",
        "password": "secret1", "unit_id": 1, **link,
    })
    assert res.status_code == 404 and db.commits == 0


def test_form_cannot_target_another_organisations_units(client, db):
    res = client.post("/forms", headers=caller(), json={
        "name": "f", "type": "questionnaire", "submitter_type": ["employee"],
        "assigned_to_units": [2], "fields": [{"question": "Q", "type": "text"}],
    })
    assert res.status_code == 404 and db.commits == 0


def test_forms_lookup_is_scoped(client, monkeypatch):
    from modules.shared.lookup import route as lookup_route

    seen = {}
    monkeypatch.setattr(lookup_route, "search_forms", lambda db, **kw: seen.update(kw) or [])
    assert client.get("/lookups/forms", headers=caller()).status_code == 200
    assert seen["organisation_id"] == OWN
