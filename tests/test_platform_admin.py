"""E0.2 T0.2.3: organisations, tenants and the permission catalogue are gated
by the platform-admin flag, never by a role permission."""

from datetime import date
from types import SimpleNamespace

import pytest

from modules.auth import repository as auth_repo
from modules.auth.service import _build_employee_claims
from modules.organisations import repository as orgs_repo
from modules.organisations.model import Organisation
from modules.roles import repository as roles_repo
from modules.tenants import repository as tenants_repo
from tests.conftest import employee_token

# Everything an organisation role could ever have held, including the old
# platform permissions. None of it may open a platform endpoint.
EVERY_ROLE_PERMISSION = [
    f"{r}:{a}"
    for r in ["organisations", "tenants", "roles"]
    for a in ["read", "create", "update", "delete"]
]

ORGS = {
    10: Organisation(id=10, name="Acme", subscription_end=date(2027, 1, 1), subscription_plan_id=1),
    20: Organisation(id=20, name="Other", subscription_end=None, subscription_plan_id=1),
}


def org_admin(**kw):
    return employee_token(organisation_id=10, is_admin=True, permissions=EVERY_ROLE_PERMISSION, **kw)


def member():
    return employee_token(organisation_id=10)


def platform():
    return employee_token(organisation_id=10, is_platform_admin=True)


@pytest.fixture
def orgs(monkeypatch):
    ORGS[10].name = "Acme"
    monkeypatch.setattr(orgs_repo, "get_organisation", lambda db, oid: ORGS.get(oid))
    monkeypatch.setattr(orgs_repo, "list_organisations", lambda db, limit, offset: list(ORGS.values()))
    monkeypatch.setattr(orgs_repo, "count_organisations", lambda db: len(ORGS))
    monkeypatch.setattr(orgs_repo, "get_organisation_by_external_id", lambda db, x: None)
    return ORGS


# ── organisations ────────────────────────────────────────────────────────────

def test_platform_admin_lists_every_organisation(client, orgs):
    res = client.get("/organisations", headers=platform())
    assert res.status_code == 200
    assert [o["id"] for o in res.json()["items"]] == [10, 20]


@pytest.mark.parametrize("who", [org_admin, member])
def test_everyone_else_lists_only_their_own_organisation(client, orgs, who):
    res = client.get("/organisations", headers=who())
    assert res.status_code == 200
    body = res.json()
    assert [o["id"] for o in body["items"]] == [10]
    assert body["total"] == 1


@pytest.mark.parametrize("who", [org_admin, member])
def test_other_organisation_is_not_found(client, orgs, who):
    assert client.get("/organisations/10", headers=who()).status_code == 200
    assert client.get("/organisations/20", headers=who()).status_code == 404


def test_platform_admin_reads_any_organisation(client, orgs):
    assert client.get("/organisations/20", headers=platform()).status_code == 200


@pytest.mark.parametrize("who", [org_admin, member])
def test_only_platform_admin_creates_or_deletes_organisations(client, orgs, db, who):
    assert client.post("/organisations", json={"name": "New"}, headers=who()).status_code == 403
    assert client.delete("/organisations/10", headers=who()).status_code == 403
    assert db.commits == 0 and db.deleted == []


def test_platform_admin_deletes_an_organisation(client, orgs, db):
    assert client.delete("/organisations/20", headers=platform()).status_code == 204
    assert db.deleted == [ORGS[20]]


def test_org_admin_edits_own_organisation(client, orgs, db):
    res = client.patch("/organisations/10", json={"name": "Acme Ltd"}, headers=org_admin())
    assert res.status_code == 200
    assert ORGS[10].name == "Acme Ltd"


def test_org_admin_cannot_edit_another_organisation(client, orgs, db):
    res = client.patch("/organisations/20", json={"name": "Hijacked"}, headers=org_admin())
    assert res.status_code == 404
    assert ORGS[20].name == "Other"


def test_member_cannot_edit_own_organisation(client, orgs, db):
    res = client.patch("/organisations/10", json={"name": "Nope"}, headers=member())
    assert res.status_code == 403
    assert db.commits == 0


@pytest.mark.parametrize(
    "change",
    [{"subscription_plan_id": 2}, {"subscription_end": "2030-01-01"}, {"external_id": "x-1"}],
)
def test_org_admin_cannot_change_billing_fields(client, orgs, db, change):
    res = client.patch("/organisations/10", json=change, headers=org_admin())
    assert res.status_code == 403
    assert db.commits == 0


def test_org_admin_form_echoing_billing_fields_still_saves(client, orgs, db):
    # the frontend edit form sends subscription_end back unchanged
    res = client.patch(
        "/organisations/10",
        json={"name": "Acme Two", "subscription_end": "2027-01-01"},
        headers=org_admin(),
    )
    assert res.status_code == 200
    assert ORGS[10].name == "Acme Two"


def test_platform_admin_changes_billing_fields(client, orgs, db):
    res = client.patch("/organisations/20", json={"subscription_plan_id": 2}, headers=platform())
    assert res.status_code == 200
    assert ORGS[20].subscription_plan_id == 2
    ORGS[20].subscription_plan_id = 1


# ── tenants ──────────────────────────────────────────────────────────────────

def test_tenants_need_platform_admin(client, monkeypatch):
    monkeypatch.setattr(tenants_repo, "list_tenants", lambda db, **kw: [], raising=False)
    monkeypatch.setattr(tenants_repo, "count_tenants", lambda db, **kw: 0, raising=False)
    assert client.get("/tenants", headers=org_admin()).status_code == 403
    assert client.post("/tenants", json={"name": "t", "email": "t@x.com"}, headers=org_admin()).status_code == 403
    assert client.get("/tenants", headers=platform()).status_code == 200


# ── permission catalogue ─────────────────────────────────────────────────────

def test_org_admin_can_read_the_catalogue(client, monkeypatch):
    monkeypatch.setattr(roles_repo, "list_permissions", lambda db: [])
    assert client.get("/roles/permissions", headers=org_admin()).status_code == 200


@pytest.mark.parametrize(
    "method, path, body",
    [
        ("post", "/roles/permissions", {"resource": "x", "action": "read"}),
        ("post", "/roles/permissions/seed", None),
        ("delete", "/roles/permissions/1", None),
    ],
)
def test_only_platform_admin_changes_the_catalogue(client, db, method, path, body):
    kwargs = {"json": body} if body is not None else {}
    res = client.request(method.upper(), path, headers=org_admin(), **kwargs)
    assert res.status_code == 403
    assert db.commits == 0


# ── the flag travels in the token ────────────────────────────────────────────

@pytest.mark.parametrize("flag", [True, False])
def test_token_claims_carry_the_platform_admin_flag(monkeypatch, flag):
    monkeypatch.setattr(auth_repo, "list_permission_names_for_role", lambda db, rid: [])
    monkeypatch.setattr(
        auth_repo, "get_role_with_permissions",
        lambda db, rid: SimpleNamespace(name="admin", is_system=True),
    )
    employee = SimpleNamespace(
        id=1, organisation_id=10, role_id=3, unit_id=None, is_platform_admin=flag
    )
    claims = _build_employee_claims(None, employee)
    assert claims["is_platform_admin"] is flag
    assert claims["is_admin"] is True  # org admin is unrelated to the flag
