"""E1.8 audit log: the change log format, what requests record, sign-ins,
answer keys, and who may read the log."""

import uuid
from datetime import datetime, timezone

import pytest

from config import AuditEnv
from modules.audit import repository as audit_repo
from modules.audit import service as audit
from modules.audit.catalogue import ACTIONS, TRACKED, Severity
from modules.audit.model import AuditEvent
from modules.auth import repository as auth_repo
from modules.auth import service as auth_service
from modules.employees.model import Employee
from modules.forms import repository as forms_repo
from modules.forms.model import Form
from modules.roles import repository as roles_repo
from modules.roles.model import Permission, Role, RolePermission
from modules.roles.permissions import PermissionKey
from tests.conftest import employee_token, make_form


def events(db, action=None):
    found = [o for o in db.added if isinstance(o, AuditEvent)]
    return [e for e in found if action is None or e.action == action]


# ── the change log format ─────────────────────────────────────────────────────

def test_only_changed_tracked_fields_are_recorded():
    spec = TRACKED["Form"]
    changes = audit.diff(spec, {"name": "A", "description": "same", "is_active": True},
                         {"name": "B", "description": "same", "is_active": True})
    assert changes == {"name": ["A", "B"]}


def test_nested_settings_become_dotted_keys():
    spec = TRACKED["Form"]
    before = {"settings": {"max_attempts": 1, "time_limit_minutes": 30, "results_revealed": False}}
    after = {"settings": {"max_attempts": 3, "time_limit_minutes": 30}}
    assert audit.diff(spec, before, after) == {
        "settings.max_attempts": [1, 3],
        "settings.results_revealed": [False, None],
    }


def test_lists_are_recorded_as_added_and_removed():
    spec = TRACKED["Form"]
    changes = audit.diff(spec, {"assigned_to_units": [1, 2, 3]}, {"assigned_to_units": [2, 3, 4]})
    assert changes == {"assigned_to_units": {"added": [4], "removed": [1]}}


def test_personal_data_is_marked_changed_but_never_stored():
    spec = TRACKED["Employee"]
    changes = audit.diff(spec, {"email": "old@x.co", "password": "h1", "role_id": 1},
                         {"email": "new@x.co", "password": "h2", "role_id": 2})
    assert changes == {"email": {"hidden": True}, "password": {"hidden": True}, "role_id": [1, 2]}
    assert "x.co" not in repr(changes) and "h2" not in repr(changes)


def test_long_values_are_cut_short(monkeypatch):
    monkeypatch.setattr(AuditEnv, "AUDIT_MAX_TEXT_CHARS", 10)
    monkeypatch.setattr(AuditEnv, "AUDIT_MAX_LIST_ITEMS", 2)
    assert audit.value("x" * 50) == "x" * 10 + "…"
    assert audit.value([1, 2, 3, 4]) == [1, 2, "…(+2)"]
    monkeypatch.setattr(AuditEnv, "AUDIT_MAX_VALUE_BYTES", 20)
    assert "too_large" in audit.value({"a": "y" * 9, "b": "z" * 9})


def test_no_change_records_nothing(db):
    role = Role(id=1, name="manager", is_system=False, organisation_id=10)
    before = audit.snapshot(role)
    assert audit.record_changes(db, role, before) is None
    assert events(db) == []


def test_escalated_fields_raise_the_severity(db):
    employee = Employee(id=3, organisation_id=10, role_id=1, is_platform_admin=False, is_active=True)
    before = audit.snapshot(employee)
    employee.is_platform_admin = True
    event = audit.record_changes(db, employee, before)
    assert event.action == "employee.updated" and event.severity == Severity.CRITICAL


def test_unknown_actions_are_refused(db):
    with pytest.raises(ValueError, match="unknown audit action"):
        audit.record(db, "form.teleported")


def test_every_catalogue_action_has_a_dotted_name_that_fits_the_column():
    assert all("." in name and len(name) <= 48 for name in ACTIONS)


# ── requests record who, from where, in which request ─────────────────────────

ROLE = Role(id=1, name="manager", is_system=False, organisation_id=10)
PERMS = {
    5: Permission(id=5, resource="forms", action="read"),
    6: Permission(id=6, resource="forms", action="delete"),
    7: Permission(id=7, resource="roles", action="update"),
}


@pytest.fixture
def role(monkeypatch):
    ROLE.name = "manager"
    ROLE.role_permissions = [
        RolePermission(role_id=1, permission_id=5, permission=PERMS[5]),
        RolePermission(role_id=1, permission_id=6, permission=PERMS[6]),
    ]
    monkeypatch.setattr(roles_repo, "get_role", lambda db, rid, org: ROLE if (rid, org) == (1, 10) else None)
    monkeypatch.setattr(roles_repo, "get_role_by_name", lambda db, name, org: None)
    monkeypatch.setattr(roles_repo, "list_permissions_by_ids", lambda db, ids: [PERMS[i] for i in ids if i in PERMS])
    monkeypatch.setattr(roles_repo, "replace_role_permissions", lambda db, role, **kw: role)
    return ROLE


def role_admin(**kw):
    return employee_token(id=4, organisation_id=10, permissions=["roles:read", "roles:update"], **kw)


def test_a_rename_is_logged_with_the_actor_ip_and_request_id(client, db, role):
    request_id = str(uuid.uuid4())
    res = client.patch("/roles/1", json={"name": "Supervisor"},
                       headers={**role_admin(), "X-Request-ID": request_id})
    assert res.status_code == 200
    assert res.headers["X-Request-ID"] == request_id
    [event] = events(db)
    assert (event.action, event.entity_type, event.entity_id) == ("role.updated", "role", 1)
    assert event.changes == {"name": ["manager", "Supervisor"]}
    assert (event.actor_id, event.organisation_id, event.ip) == (4, 10, "testclient")
    assert event.correlation_id == uuid.UUID(request_id)
    assert event.severity == Severity.NOTICE


def test_a_request_id_that_isnt_a_uuid_is_replaced(client, role):
    res = client.get("/roles/1", headers={**role_admin(), "X-Request-ID": "<script>"})
    assert uuid.UUID(res.headers["X-Request-ID"])


def test_permission_changes_list_the_keys_added_and_removed(client, db, role):
    res = client.put("/roles/1/permissions", json={"permission_ids": [5, 7]}, headers=role_admin())
    assert res.status_code == 200, res.text
    [event] = events(db, "role.permissions_changed")
    assert event.changes == {"permissions": {"added": ["roles:update"], "removed": ["forms:delete"]}}
    assert event.severity == Severity.WARNING


# ── sign-ins ──────────────────────────────────────────────────────────────────

@pytest.fixture
def accounts(monkeypatch):
    person = Employee(id=3, organisation_id=10, email="sara@x.co", is_active=True, first_name="Sara", last_name="Ali",
                      password=auth_service.hash_password("right"), role_id=None, unit_id=None,
                      is_platform_admin=False, refresh_tokens=[])
    monkeypatch.setattr(auth_repo, "get_employee_by_email", lambda db, email: person if email == "sara@x.co" else None)
    monkeypatch.setattr(auth_repo, "get_employee_by_id", lambda db, eid: person if eid == 3 else None)
    monkeypatch.setattr(audit_repo, "count_failed_logins", lambda db, **kw: 0)
    # the real one saves the session's refresh token id, and commits
    monkeypatch.setattr(auth_repo, "add_refresh_jti", lambda db, *a: db.commit())
    return person


def test_a_sign_in_is_logged(client, db, accounts):
    res = client.post("/auth/employee/login", json={"email": "sara@x.co", "password": "right"})
    assert res.status_code == 200
    [event] = events(db)
    assert (event.action, event.actor_id, event.entity_id, event.organisation_id) == ("auth.login", 3, 3, 10)


def test_a_wrong_password_is_logged_against_the_account(client, db, accounts):
    res = client.post("/auth/employee/login", json={"email": "sara@x.co", "password": "wrong"})
    assert res.status_code == 401
    [event] = events(db)
    assert (event.action, event.entity_id, event.organisation_id, event.actor_id) == ("auth.login_failed", 3, 10, None)
    assert event.data == {"reason": "wrong_password"} and event.severity == Severity.WARNING
    assert db.commits == 1


def test_an_unknown_account_is_logged_without_the_email(client, db, accounts):
    res = client.post("/auth/employee/login", json={"email": "nobody@x.co", "password": "x"})
    assert res.status_code == 401
    [event] = events(db)
    assert event.organisation_id is None and event.entity_id is None
    assert event.data == {"reason": "unknown_account"}
    assert "nobody" not in repr(vars(event))


def test_many_failures_from_one_ip_raise_the_severity(client, db, accounts, monkeypatch):
    monkeypatch.setattr(audit_repo, "count_failed_logins", lambda db, **kw: AuditEnv.AUDIT_FAILED_LOGIN_ALERT - 1)
    client.post("/auth/employee/login", json={"email": "sara@x.co", "password": "wrong"})
    [event] = events(db)
    assert event.severity == Severity.ERROR


def test_a_disabled_account_is_logged(client, db, accounts):
    accounts.is_active = False
    res = client.post("/auth/employee/login", json={"email": "sara@x.co", "password": "right"})
    assert res.status_code == 403
    assert [e.action for e in events(db)] == ["auth.login_blocked"]


# ── forms: publishing and answer keys ─────────────────────────────────────────

def test_publishing_a_changed_answer_key_is_logged(client, db, monkeypatch):
    form = make_form()  # published as version 1, with right answers
    form.fields[0].right_answer = "B"
    form.fields[1].score_weight = 2.0

    def add_version(db, form, *, snapshot, published_by):
        from tests.conftest import republish
        version = republish(form)
        version.snapshot = snapshot
        return version

    monkeypatch.setattr(forms_repo, "get_form", lambda db, fid: form)
    monkeypatch.setattr(forms_repo, "add_version", add_version)
    monkeypatch.setattr(forms_repo, "form_has_submissions", lambda db, fid: False)
    headers = employee_token(id=1, organisation_id=10, permissions=["forms:update"])
    res = client.post("/forms/7/publish", headers=headers)
    assert res.status_code == 200, res.text
    published = events(db, "form.published")[0]
    assert published.data["version"] == 2 and published.data["questions_changed"] == 2
    [key] = events(db, "form.answer_key_changed")
    assert key.changes == {"k101.right_answer": ["A", "B"], "k102.score_weight": [1.0, 2.0]}
    assert key.data["questions"] == {"k101": "Pick A", "k102": "Explain"}
    assert key.severity == Severity.WARNING


def test_the_first_publish_has_no_answer_key_change():
    changes, _ = audit_answer_key(None, {"fields": [{"key": "k1", "right_answer": "A"}]})
    assert changes == {}


def audit_answer_key(old, new):
    from modules.forms.service import _answer_key_changes
    return _answer_key_changes(old, new)


# ── reading the log ───────────────────────────────────────────────────────────

def stored(**kw):
    data = dict(id=9, occurred_at=datetime(2026, 11, 20, tzinfo=timezone.utc), organisation_id=10,
                severity=int(Severity.WARNING), action="employee.updated", entity_type="employee",
                entity_id=3, actor_id=4, ip="10.0.0.1", correlation_id=None,
                changes={"role_id": [1, 2], "email": {"hidden": True}, "assigned_units": {"added": [7], "removed": []}},
                data=None)
    data.update(kw)
    return AuditEvent(**data)


def test_reading_needs_audit_read(client):
    assert client.get("/audit/events", headers=employee_token(permissions=["roles:read"])).status_code == 403
    assert client.get("/audit/catalogue", headers=employee_token(permissions=["roles:read"])).status_code == 403


def test_the_log_is_scoped_to_the_callers_organisation_and_names_its_records(client, monkeypatch):
    seen = {}

    def list_events(db, **kw):
        seen.update(kw)
        return [stored()], "next"

    def names(db, *, organisation_id, wanted):
        seen["names_org"] = organisation_id
        seen["wanted"] = wanted
        return {"employee": {3: "Sara Ali", 4: "Omar"}, "role": {1: "agent", 2: "manager"}, "unit": {7: "Cairo"}}

    monkeypatch.setattr(audit_repo, "list_events", list_events)
    monkeypatch.setattr(audit_repo, "names", names)
    res = client.get("/audit/events?min_severity=warning&action_prefix=employee.&limit=10",
                     headers=employee_token(organisation_id=10, permissions=["audit:read"]))
    assert res.status_code == 200, res.text
    body = res.json()
    assert seen["organisation_id"] == 10 and seen["names_org"] == 10
    assert seen["min_severity"] == int(Severity.WARNING) and seen["action_prefix"] == "employee."
    assert seen["wanted"] == {"employee": {3, 4}, "role": {1, 2}, "unit": {7}, "form": set()}
    [item] = body["items"]
    assert item["severity"] == "warning" and item["action_label"] == "Employee changed"
    assert item["changes"] == [
        {"field": "role_id", "kind": "value", "old": 1, "new": 2, "added": [], "removed": []},
        {"field": "email", "kind": "hidden", "old": None, "new": None, "added": [], "removed": []},
        {"field": "assigned_units", "kind": "set", "old": None, "new": None, "added": [7], "removed": []},
    ]
    assert body["names"]["role"] == {"1": "agent", "2": "manager"} and body["next_cursor"] == "next"


def test_a_bad_cursor_is_a_422(client):
    res = client.get("/audit/events?cursor=nonsense", headers=employee_token(permissions=["audit:read"]))
    assert res.status_code == 422


def test_cursors_round_trip():
    row = stored(id=41)
    assert audit_repo.decode_cursor(audit_repo.encode_cursor(row)) == (row.occurred_at, 41)


def test_platform_entries_are_for_platform_admins_only(client, monkeypatch):
    seen = {}
    monkeypatch.setattr(audit_repo, "list_events", lambda db, **kw: seen.update(kw) or ([], None))
    monkeypatch.setattr(audit_repo, "names", lambda db, **kw: {})
    org_admin = employee_token(permissions=["audit:read"], is_admin=True)
    assert client.get("/audit/platform-events", headers=org_admin).status_code == 403
    res = client.get("/audit/platform-events", headers=employee_token(is_platform_admin=True))
    assert res.status_code == 200 and seen["organisation_id"] is None


def test_the_catalogue_lists_severities_in_order(client):
    res = client.get("/audit/catalogue", headers=employee_token(permissions=["audit:read"]))
    assert [s["name"] for s in res.json()["severities"]] == ["debug", "info", "notice", "warning", "error", "critical"]


# ── permissions and retention ─────────────────────────────────────────────────

def test_audit_can_only_be_read_and_mentions_left_the_catalogue():
    pairs = set(PermissionKey.all_pairs())
    assert ("audit", "read") in pairs
    assert not {("audit", a) for a in ("create", "update", "delete")} & pairs
    assert not {r for r, _ in pairs} & set(PermissionKey.DROPPED_RESOURCES)


def test_purge_skips_severities_kept_for_ever(db, monkeypatch):
    purged = []

    def purge(db, *, severity, before, batch_size):
        purged.append(severity)
        return 2

    monkeypatch.setattr(audit_repo, "purge", purge)
    monkeypatch.setitem(AuditEnv.AUDIT_RETENTION_DAYS, "critical", 0)
    counts = audit.purge(db)
    assert int(Severity.CRITICAL) not in purged and "critical" not in counts
    [event] = events(db, "audit.purged")
    assert event.data == counts and event.organisation_id is None and db.commits == 1


# ── one record's history (on the record's own page) ───────────────────────────

@pytest.fixture
def history(monkeypatch):
    seen = {}

    def list_events(db, **kw):
        seen.update(kw)
        return [stored(entity_type=kw["entity_type"], entity_id=kw["entity_id"], ip="10.0.0.1",
                       correlation_id=uuid.uuid4())], None

    monkeypatch.setattr(audit_repo, "list_events", list_events)
    monkeypatch.setattr(audit_repo, "names", lambda db, **kw: {})
    return seen


def test_anyone_who_may_open_a_role_sees_its_history_without_ips(client, history, monkeypatch):
    monkeypatch.setattr(roles_repo, "get_role", lambda db, rid, org: ROLE if (rid, org) == (1, 10) else None)
    res = client.get("/audit/records/role/1", headers=employee_token(organisation_id=10, permissions=["roles:read"]))
    assert res.status_code == 200, res.text
    assert history["organisation_id"] == 10 and (history["entity_type"], history["entity_id"]) == ("role", 1)
    # sign-ins stay in the audit log
    assert history["exclude_action_prefixes"] == ("auth.",)
    [item] = res.json()["items"]
    assert item["ip"] is None and item["correlation_id"] is None


def test_auditors_also_see_the_ip(client, history, monkeypatch):
    monkeypatch.setattr(roles_repo, "get_role", lambda db, rid, org: ROLE)
    res = client.get("/audit/records/role/1", headers=employee_token(permissions=["roles:read", "audit:read"]))
    assert res.json()["items"][0]["ip"] == "10.0.0.1"


def test_a_record_the_caller_cannot_open_has_no_history_for_them(client, history, monkeypatch):
    monkeypatch.setattr(roles_repo, "get_role", lambda db, rid, org: None)  # another organisation's
    assert client.get("/audit/records/role/2", headers=employee_token(permissions=["roles:read"])).status_code == 404
    assert client.get("/audit/records/role/1", headers=employee_token(permissions=["forms:read"])).status_code == 403
    assert client.get("/audit/records/submission/1", headers=employee_token(permissions=["audit:read"])).status_code == 404
    assert history == {}


def test_respondents_see_that_an_answer_key_changed_but_not_the_answers(client, monkeypatch):
    form = make_form(created_by=99)
    monkeypatch.setattr(forms_repo, "get_form", lambda db, fid: form)
    monkeypatch.setattr(audit_repo, "names", lambda db, **kw: {})
    monkeypatch.setattr(audit_repo, "list_events", lambda db, **kw: ([stored(
        action="form.answer_key_changed", entity_type="form", entity_id=7,
        changes={"k101.right_answer": ["A", "B"]}, data={"version": 2, "questions": {"k101": "Pick A"}},
    )], None))
    agent = employee_token(id=5, permissions=["forms:read"])
    [item] = client.get("/audit/records/form/7", headers=agent).json()["items"]
    assert item["changes"] == [{"field": "k101.right_answer", "kind": "hidden", "old": None, "new": None,
                                "added": [], "removed": []}]
    assert item["data"] == {"version": 2}
    manager = employee_token(id=6, permissions=["forms:read", "forms:update"])
    [item] = client.get("/audit/records/form/7", headers=manager).json()["items"]
    assert item["changes"][0]["new"] == "B"
