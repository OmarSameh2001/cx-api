"""T0.6.1 findings, fixed: units, assignments, the tenant-scoped modules,
employee links, form unit targeting and the forms lookup all stay inside the
caller's organisation. (The end-to-end version against the real database is
cx-front/e2e/isolation.spec.ts.)"""

import uuid
from types import SimpleNamespace

import pytest

from modules.assignments import repository as assignments_repo
from modules.employees import repository as employees_repo
from modules.keywords import repository as keywords_repo
from modules.notification_rules import repository as rules_repo
from modules.tenants import repository as tenants_repo
from modules.units import repository as units_repo
from tests.conftest import employee_token

OWN, OTHER = 10, 20
TENANT_OTHER = uuid.uuid4()
TENANT_OWN = uuid.uuid4()
EVERYTHING = [
    f"{r}:{a}"
    for r in ["units", "assignments", "keywords", "mentions", "notification_rules", "notification_deliveries",
              "employees", "forms"]
    for a in ["read", "create", "update", "delete"]
]


def caller(**kw):
    return employee_token(organisation_id=OWN, permissions=EVERYTHING, assigned_unit_ids=[1], **kw)


UNITS = {1: SimpleNamespace(id=1, organisation_id=OWN), 2: SimpleNamespace(id=2, organisation_id=OTHER)}


@pytest.fixture(autouse=True)
def world(monkeypatch):
    monkeypatch.setattr(units_repo, "get_unit", lambda db, uid: UNITS.get(uid))
    tenants = {TENANT_OWN: SimpleNamespace(organisation_id=OWN), TENANT_OTHER: SimpleNamespace(organisation_id=OTHER)}
    monkeypatch.setattr(tenants_repo, "get_tenant", lambda db, tid: tenants.get(tid))


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


# ── tenant-scoped modules ───────────────────────────────────────────────────

def test_listing_another_organisations_tenant_is_not_found(client):
    for path in ("/keywords", "/mentions", "/notification-rules", "/notification-deliveries"):
        res = client.get(f"{path}?tenant_id={TENANT_OTHER}", headers=caller())
        assert res.status_code == 404, path


def test_another_organisations_keyword_is_not_found(client, db, monkeypatch):
    kw = SimpleNamespace(id=uuid.uuid4(), tenant_id=TENANT_OTHER)
    monkeypatch.setattr(keywords_repo, "get_keyword", lambda db, kid: kw)
    for method in ("GET", "PATCH", "DELETE"):
        body = {"json": {"is_active": False}} if method == "PATCH" else {}
        assert client.request(method, f"/keywords/{kw.id}", headers=caller(), **body).status_code == 404
    assert db.commits == 0 and db.deleted == []


def test_cannot_create_in_another_organisations_tenant(client, db):
    res = client.post("/keywords", json={"phrase": "x", "tenant_id": str(TENANT_OTHER)}, headers=caller())
    assert res.status_code == 404 and db.added == []


def test_delivery_rule_must_be_the_tenants_own(client, db, monkeypatch):
    rule = SimpleNamespace(tenant_id=TENANT_OTHER)
    monkeypatch.setattr(rules_repo, "get_notification_rule", lambda db, rid: rule)
    res = client.post("/notification-deliveries", headers=caller(), json={
        "tenant_id": str(TENANT_OWN), "notification_rule_id": str(uuid.uuid4()),
        "source_module": "m", "channel": "email", "recipient": "a@b.co", "status": "sent",
    })
    assert res.status_code == 404 and db.added == []


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
