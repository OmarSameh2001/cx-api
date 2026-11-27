"""Fixes from the M0+M1 review: another organisation's submissions are 404,
the session list is changed under a row lock, the admin role can't be
handed out (or stripped) by non-admins, only our own proxies' IPs are
trusted, and two first submissions with one email don't collide."""

from types import SimpleNamespace

import pytest
from sqlalchemy.exc import IntegrityError

from config import AuthEnv
from common.request_context import client_ip_from
from modules.auth import repository as auth_repo
from modules.customers import repository as customers_repo
from modules.customers.model import Customer
from modules.audit import repository as audit_repo
from modules.employees import repository as employees_repo
from modules.employees.model import Employee
from modules.forms import repository as forms_repo
from modules.roles import repository as roles_repo
from modules.submissions import repository as subs_repo
from tests.conftest import employee_token, make_form, make_submission


# --- 1. another organisation's submissions and forms are missing --------------------


@pytest.fixture
def other_orgs_submission(monkeypatch):
    form = make_form(organisation_id=20, created_by=99)
    sub = make_submission(form, user_id=1, status="in_progress")  # same employee id, other org
    monkeypatch.setattr(subs_repo, "get_submission", lambda db, sid: sub)
    return sub


@pytest.mark.parametrize(
    "method, path, body",
    [
        ("GET", "/submissions/500", None),
        ("GET", "/submissions/500/detail", None),
        ("GET", "/submissions/500/form", None),
        ("PATCH", "/submissions/500/draft", {"answers": {}}),
        ("POST", "/submissions/500/submit", {"answers": {}}),
        ("POST", "/submissions/500/reveal", None),
        ("DELETE", "/submissions/500", None),
    ],
)
def test_another_organisations_submission_is_missing_and_left_alone(
    client, db, other_orgs_submission, method, path, body
):
    headers = employee_token(id=1, organisation_id=10, is_admin=True)
    res = client.request(method, path, json=body, headers=headers)
    assert res.status_code == 404, res.text
    assert db.commits == 0 and db.added == []


def test_an_expired_attempt_is_not_expired_by_someone_who_cant_see_it(client, db, monkeypatch):
    from datetime import datetime, timezone

    form = make_form(created_by=99)
    sub = make_submission(form, user_id=2, expires_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    monkeypatch.setattr(subs_repo, "get_submission", lambda db, sid: sub)
    res = client.get("/submissions/500", headers=employee_token(id=3, organisation_id=10))
    assert res.status_code == 403
    assert sub.status == "in_progress" and db.commits == 0


@pytest.mark.parametrize("state", [{"is_active": False}, {"is_archived": True}, {"submitter_type": ["customer"]}])
def test_starting_another_organisations_form_is_404_whatever_its_state(client, monkeypatch, state):
    form = make_form(organisation_id=20, **state)
    monkeypatch.setattr(forms_repo, "get_form", lambda db, fid: form)
    res = client.post("/submissions/start", json={"form_id": form.id},
                      headers=employee_token(organisation_id=10))
    assert res.status_code == 404


# --- 2. the session list is changed under a row lock --------------------------------


class _LockingDb:
    def __init__(self, row):
        self.row, self.gets, self.commits = row, [], 0

    def get(self, model, oid, **kw):
        self.gets.append(kw)
        return self.row

    def commit(self):
        self.commits += 1


@pytest.mark.parametrize(
    "call",
    [
        lambda db: auth_repo.add_refresh_jti(db, "employee", 1, "new"),
        lambda db: auth_repo.remove_refresh_jti(db, "employee", 1, "old"),
        lambda db: auth_repo.clear_refresh_jtis(db, "employee", 1),
    ],
)
def test_changing_the_session_list_locks_and_rereads_the_account(call):
    db = _LockingDb(SimpleNamespace(refresh_tokens=["old"]))
    call(db)
    assert db.gets == [{"with_for_update": True, "populate_existing": True}]


def test_a_refresh_token_works_once():
    db = _LockingDb(SimpleNamespace(refresh_tokens=["old"]))
    assert auth_repo.remove_refresh_jti(db, "employee", 1, "old") == 1
    assert auth_repo.remove_refresh_jti(db, "employee", 1, "old") == 0


# --- 3. the admin role ---------------------------------------------------------------

ROLES = {
    1: SimpleNamespace(id=1, organisation_id=10, is_system=True, name="admin", role_permissions=[]),
    2: SimpleNamespace(id=2, organisation_id=10, is_system=False, name="manager", role_permissions=[]),
}


@pytest.fixture
def staff(monkeypatch):
    def person(eid, role_id):
        return Employee(id=eid, organisation_id=10, unit_id=1, role_id=role_id, first_name="F",
                        last_name="L", username=f"u{eid}", email=f"u{eid}@x.co", is_active=True,
                        assigned_units=[])

    people = {4: person(4, 2), 5: person(5, 2), 6: person(6, 1)}  # 4 edits; 6 is an admin
    monkeypatch.setattr(employees_repo, "get_employee", lambda db, eid: people.get(eid))
    monkeypatch.setattr(roles_repo, "get_role",
                        lambda db, rid, oid: ROLES.get(rid) if ROLES.get(rid) and ROLES[rid].organisation_id == oid else None)
    monkeypatch.setattr(employees_repo, "update_employee",
                        lambda db, e, data: [setattr(e, k, v) for k, v in data.items()] and e)
    return people


def _editor(**kw):
    return employee_token(id=4, organisation_id=10, unit_id=1, assigned_unit_ids=[1],
                          permissions=["employees:update", "employees:create", "employees:delete"], **kw)


def _code(res):
    return res.json().get("error")


def test_a_non_admin_cannot_give_the_admin_role(client, staff):
    res = client.patch("/employees/5", json={"role_id": 1}, headers=_editor())
    assert res.status_code == 403 and _code(res) == "employees.admin_role_admin_only"
    assert staff[5].role_id == 2


def test_a_non_admin_cannot_create_an_admin(client, staff, monkeypatch):
    monkeypatch.setattr(employees_repo, "get_employee_by_email", lambda db, e: None)
    monkeypatch.setattr(employees_repo, "get_employee_by_username", lambda db, u: None)
    res = client.post("/employees", headers=_editor(), json={
        "first_name": "A", "last_name": "B", "username": "ab", "email": "ab@x.co",
        "password": "secret123", "unit_id": 1, "role_id": 1,
    })
    assert res.status_code == 403 and _code(res) == "employees.admin_role_admin_only"


def test_nobody_changes_their_own_role(client, staff):
    res = client.patch("/employees/4", json={"role_id": 1}, headers=_editor(is_admin=True))
    assert res.status_code == 403 and _code(res) == "employees.own_role"


@pytest.mark.parametrize("change", [{"email": "mine@x.co"}, {"role_id": 2}, {"is_active": False}])
def test_a_non_admin_cannot_change_an_admins_account(client, staff, monkeypatch, change):
    monkeypatch.setattr(employees_repo, "get_employee_by_email", lambda db, e: None)
    res = client.patch("/employees/6", json=change, headers=_editor())
    assert res.status_code == 403 and _code(res) == "employees.admin_admin_only"


def test_a_non_admin_cannot_delete_an_admin(client, staff):
    res = client.delete("/employees/6", headers=_editor())
    assert res.status_code == 403 and _code(res) == "employees.admin_admin_only"


def test_the_admin_can_give_the_admin_role(client, db, staff):
    res = client.patch("/employees/5", json={"role_id": 1}, headers=_editor(is_admin=True))
    assert res.status_code == 200, res.text
    assert staff[5].role_id == 1 and db.commits == 1


def test_a_non_admin_still_edits_other_staff(client, db, staff):
    res = client.patch("/employees/5", json={"first_name": "New"}, headers=_editor())
    assert res.status_code == 200, res.text


@pytest.mark.parametrize(
    "method, path, body",
    [
        ("PUT", "/roles/1/permissions", {"permission_ids": []}),
        ("POST", "/roles/1/permissions", {"permission_ids": [3]}),
        ("DELETE", "/roles/1/permissions/3", None),
    ],
)
def test_the_admin_roles_permissions_are_locked(client, db, monkeypatch, method, path, body):
    monkeypatch.setattr(roles_repo, "get_role", lambda db, rid, oid: ROLES.get(rid))
    headers = employee_token(organisation_id=10, is_admin=True, permissions=["roles:update"])
    res = client.request(method, path, json=body, headers=headers)
    assert res.status_code == 403 and _code(res) == "roles.system_permissions_locked"
    assert db.commits == 0


# --- 4. only our own proxies' X-Forwarded-For entries count ----------------------------


@pytest.mark.parametrize(
    "trusted, forwarded, expected",
    [
        (1, "6.6.6.6, 203.0.113.5", "203.0.113.5"),  # the client sent 6.6.6.6
        (2, "198.51.100.1, 203.0.113.5, 10.0.0.1", "203.0.113.5"),
        (0, "6.6.6.6", "10.9.9.9"),  # reached directly: the header is ignored
        (1, None, "10.9.9.9"),
        (3, "203.0.113.5", "203.0.113.5"),
    ],
)
def test_client_ip_trusts_only_our_proxies(monkeypatch, trusted, forwarded, expected):
    monkeypatch.setattr(AuthEnv, "TRUSTED_PROXY_COUNT", trusted)
    assert client_ip_from(forwarded, "10.9.9.9") == expected


def test_a_made_up_ip_doesnt_escape_the_login_limit(client, monkeypatch):
    monkeypatch.setattr(AuthEnv, "TRUSTED_PROXY_COUNT", 0)
    monkeypatch.setattr(auth_repo, "get_employee_by_email", lambda db, e: None)
    monkeypatch.setattr(audit_repo, "count_failed_logins", lambda db, **kw: 0)
    from config import SSOEnv

    codes = [
        client.post("/auth/employee/login", json={"email": "x@x.co", "password": "p"},
                    headers={"X-Forwarded-For": f"6.6.6.{i}"}).status_code
        for i in range(SSOEnv.LOGINS_PER_MINUTE_PER_IP + 1)
    ]
    assert codes[-1] == 429


# --- 7. two first submissions with the same email ---------------------------------------


def test_a_customer_added_by_a_parallel_submission_is_reused(client, db, monkeypatch):
    form = make_form(type="questionnaire", max_attempts=2)
    monkeypatch.setattr(forms_repo, "get_form_by_token", lambda db, t: form)
    monkeypatch.setattr(subs_repo, "count_finalized_attempts", lambda db, **kw: 0)
    winner = Customer(id=77, organisation_id=10, email="ann@acme.io", first_name="Ann", last_name="Lee")
    lookups = iter([None, winner])  # not there yet, then committed by the other request
    monkeypatch.setattr(customers_repo, "get_by_email", lambda db, **kw: next(lookups))

    def collide(db, **kw):
        raise IntegrityError("insert", {}, Exception("duplicate key"))

    monkeypatch.setattr(customers_repo, "create", collide)
    res = client.post("/public/forms/tok/submit", json={
        "customer": {"email": "ann@acme.io", "first_name": "Ann", "last_name": "Lee"},
        "answers": {"101": "A"},
    })
    assert res.status_code == 201, res.text
    sub = next(o for o in db.added if type(o).__name__ == "Submission")
    assert sub.customer_id == 77
