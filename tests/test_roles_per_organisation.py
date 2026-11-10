"""E0.2 T0.2.1 / T0.2.2: roles belong to one organisation, and every role
endpoint only sees the caller's organisation."""

import pytest

from modules.employees import repository as employees_repo
from modules.organisations import repository as orgs_repo
from modules.organisations.model import Organisation
from modules.roles import repository as roles_repo
from modules.roles.model import Role
from modules.roles.permissions import DEFAULT_ROLES, PermissionKey
from tests.conftest import employee_token

ALL_ROLE_PERMS = ["roles:read", "roles:create", "roles:update", "roles:delete"]

# role 1 belongs to org 10 (the caller's), role 2 to org 20
ROLES = {
    1: Role(id=1, name="manager", is_system=False, organisation_id=10),
    2: Role(id=2, name="manager", is_system=False, organisation_id=20),
}


@pytest.fixture
def roles(monkeypatch):
    for r in ROLES.values():
        r.role_permissions = []
        r.employees = []

    def get_role(db, role_id, organisation_id):
        # fixture roles, plus any the request just created
        created = {o.id: o for o in db.added if isinstance(o, Role)}
        role = ROLES.get(role_id) or created.get(role_id)
        return role if role is not None and role.organisation_id == organisation_id else None

    def get_role_by_name(db, name, organisation_id):
        return next(
            (r for r in ROLES.values() if r.name == name and r.organisation_id == organisation_id),
            None,
        )

    monkeypatch.setattr(roles_repo, "get_role", get_role)
    monkeypatch.setattr(roles_repo, "get_role_by_name", get_role_by_name)
    return ROLES


def headers(**kw):
    return employee_token(organisation_id=10, permissions=ALL_ROLE_PERMS, **kw)


# ── list / read ──────────────────────────────────────────────────────────────

def test_list_roles_is_scoped_to_callers_organisation(client, monkeypatch):
    seen = {}

    def list_roles(db, *, organisation_id, limit, offset):
        seen["list"] = organisation_id
        return [ROLES[1]]

    def count_roles(db, *, organisation_id):
        seen["count"] = organisation_id
        return 1

    monkeypatch.setattr(roles_repo, "list_roles", list_roles)
    monkeypatch.setattr(roles_repo, "count_roles", count_roles)

    res = client.get("/roles", headers=headers())
    assert res.status_code == 200
    assert seen == {"list": 10, "count": 10}
    assert [r["id"] for r in res.json()["items"]] == [1]


def test_own_role_is_readable(client, roles):
    assert client.get("/roles/1", headers=headers()).status_code == 200


@pytest.mark.parametrize(
    "method, path, body",
    [
        ("get", "/roles/2", None),
        ("patch", "/roles/2", {"name": "renamed"}),
        ("delete", "/roles/2", None),
        ("put", "/roles/2/permissions", {"permission_ids": []}),
        ("post", "/roles/2/permissions", {"permission_ids": [1]}),
        ("delete", "/roles/2/permissions/1", None),
    ],
)
def test_other_organisations_role_is_not_found(client, roles, db, method, path, body):
    kwargs = {"json": body} if body is not None else {}
    res = client.request(method.upper(), path, headers=headers(), **kwargs)
    assert res.status_code == 404
    assert db.commits == 0 and db.deleted == []


# ── create / rename ──────────────────────────────────────────────────────────

def test_role_name_only_has_to_be_unique_inside_the_organisation(client, roles, db):
    # "manager" exists in org 20 too, but org 10's caller is asked about org 10 only
    res = client.post("/roles", json={"name": "manager"}, headers=headers())
    assert res.status_code == 409  # org 10 already has one

    res = client.post(
        "/roles",
        json={"name": "manager"},
        headers=employee_token(organisation_id=30, permissions=ALL_ROLE_PERMS),
    )
    assert res.status_code == 201
    created = [o for o in db.added if isinstance(o, Role)]
    assert len(created) == 1 and created[0].organisation_id == 30


def test_api_cannot_create_a_system_role(client, roles, db):
    res = client.post("/roles", json={"name": "sneaky", "is_system": True}, headers=headers())
    assert res.status_code == 201
    assert res.json()["is_system"] is False
    (role,) = [o for o in db.added if isinstance(o, Role)]
    assert role.is_system is False


def test_created_role_belongs_to_callers_organisation(client, roles, db):
    res = client.post("/roles", json={"name": "auditor"}, headers=headers())
    assert res.status_code == 201
    (role,) = [o for o in db.added if isinstance(o, Role)]
    assert role.organisation_id == 10


# ── employees can only get a role from their own organisation ────────────────

@pytest.fixture
def no_employee_conflicts(monkeypatch):
    monkeypatch.setattr(employees_repo, "get_employee_by_email", lambda db, e: None)
    monkeypatch.setattr(employees_repo, "get_employee_by_username", lambda db, u: None)
    monkeypatch.setattr(employees_repo, "get_employee_by_external_id", lambda db, x: None)


def test_employee_cannot_be_given_another_organisations_role(
    client, roles, db, no_employee_conflicts
):
    res = client.post(
        "/employees",
        json={
            "first_name": "E", "last_name": "V", "username": "eve",
            "email": "eve@example.com", "password": "secret1",
            "unit_id": 5, "role_id": 2,
        },
        headers=employee_token(
            organisation_id=10, permissions=["employees:create"], assigned_unit_ids=[5]
        ),
    )
    assert res.status_code == 404
    assert res.json()["detail"] == "Role not found"
    assert db.commits == 0


# ── default roles when an organisation is created ────────────────────────────

def test_new_organisation_gets_the_default_roles(client, db, monkeypatch):
    monkeypatch.setattr(orgs_repo, "get_organisation_by_external_id", lambda db, x: None)
    monkeypatch.setattr(roles_repo, "get_permission_by_pair", lambda db, r, a: None)
    monkeypatch.setattr(roles_repo, "get_role_by_name", lambda db, n, o: None)
    monkeypatch.setattr(
        orgs_repo,
        "get_organisation",
        lambda db, oid: next(o for o in db.added if isinstance(o, Organisation)),
    )

    res = client.post(
        "/organisations", json={"name": "Beta"}, headers=employee_token(is_platform_admin=True)
    )
    assert res.status_code == 201
    assert db.commits == 1  # org and roles in one transaction

    org = next(o for o in db.added if isinstance(o, Organisation))
    roles = {r.name: r for r in db.added if isinstance(r, Role)}
    assert set(roles) == {name for name, _, _ in DEFAULT_ROLES}
    assert all(r.organisation_id == org.id for r in roles.values())
    assert roles["admin"].is_system and not roles["manager"].is_system


def test_platform_resources_are_not_role_permissions():
    resources = {r for r, _ in PermissionKey.all_pairs()}
    assert resources.isdisjoint(PermissionKey.PLATFORM_RESOURCES)
    for _, _, keys in DEFAULT_ROLES:
        assert keys is None or {r for r, _ in keys}.isdisjoint(PermissionKey.PLATFORM_RESOURCES)
