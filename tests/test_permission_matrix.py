"""Permission matrix, as plain unit tests on the existing harness.

1. Static: each guarded route's required permission should match its
   resource and HTTP method (GET->read, POST->create, PATCH/PUT->update,
   DELETE->delete), and every permission it needs should be one a role can
   actually hold.
2. Runtime: an employee holding only the default "agent" role's permissions
   gets 403 on every GET/DELETE route that needs a permission they lack, and
   is not refused on the ones they hold.
"""

import re

import pytest
from fastapi.routing import APIRoute

import main
from modules.roles.permissions import DEFAULT_ROLES, PermissionKey
from tests.conftest import employee_token

METHOD_ACTION = {"GET": "read", "POST": "create", "PATCH": "update", "PUT": "update", "DELETE": "delete"}
HOLDABLE = {f"{r}:{a}" for r, a in PermissionKey.all_pairs()}
AGENT = next(keys for name, _, keys in DEFAULT_ROLES if name == "agent")
AGENT_PERMS = {f"{r}:{a}" for r, a in AGENT}


def _needed(endpoint):
    for cell in endpoint.__closure__ or []:
        fn = cell.cell_contents
        if callable(fn) and getattr(fn, "__name__", "") == "_check":
            for c in fn.__closure__:
                if isinstance(c.cell_contents, tuple):
                    return c.cell_contents
    return None


GUARDED = [
    (method, r.path, _needed(r.endpoint))
    for r in main.app.routes
    if isinstance(r, APIRoute) and hasattr(r.endpoint, "__wrapped__")
    for method in sorted(r.methods)
]


# Deliberate departures from "resource:<action for the HTTP method>".
EXCEPTIONS = {
    # adding or removing a role's permissions edits the role
    ("POST", "/roles/{role_id}/permissions"): "roles:update",
    ("DELETE", "/roles/{role_id}/permissions/{permission_id}"): "roles:update",
    # drafting a form with AI is part of creating one
    ("POST", "/ai/forms/generate"): "forms:create",
}
# Needs tenants:*, which no role can hold since platform admin became a flag
# (E0.2); the router is to be unmounted (E0.3).
DEAD_ROUTES = "/platform-configs"


def _resource(path):
    first = path.strip("/").split("/")[0]
    return first.replace("-", "_")


@pytest.mark.parametrize("method, path, needed", GUARDED, ids=[f"{m} {p}" for m, p, _ in GUARDED])
def test_permission_matches_route(method, path, needed):
    if path.startswith(DEAD_ROUTES):
        pytest.skip("platform-configs: unusable until unmounted (E0.3)")
    if (method, path) in EXCEPTIONS:
        assert needed == (EXCEPTIONS[(method, path)],)
        return
    problems = []
    for perm in needed:
        resource, action = perm.split(":")
        if perm not in HOLDABLE:
            problems.append(f"{perm} is not a permission any role can hold")
        if resource != _resource(path):
            problems.append(f"{perm} guards a /{_resource(path)} route")
        if action != METHOD_ACTION[method]:
            problems.append(f"{perm} on a {method} (expected :{METHOD_ACTION[method]})")
    assert not problems, "; ".join(problems)


SAMPLE = {"uuid": "00000000-0000-0000-0000-000000000001", "int": "1"}


def _fill(path):
    return re.sub(r"\{(\w+)\}", lambda m: SAMPLE["uuid"] if m.group(1) in {
        "keyword_id", "mention_id", "rule_id", "delivery_id", "config_id", "tenant_id"} else SAMPLE["int"], path)


RUNTIME = [(m, p, n) for m, p, n in GUARDED if m in ("GET", "DELETE")]


@pytest.mark.parametrize("method, path, needed", RUNTIME, ids=[f"{m} {p}" for m, p, _ in RUNTIME])
def test_agent_is_refused_exactly_where_their_role_says(client, method, path, needed):
    url = _fill(path)
    if "tenant" not in url and _resource(path) in {"keywords", "mentions", "notification_rules",
                                                   "notification_deliveries", "platform_configs"} and "{" not in path:
        url += f"?tenant_id={SAMPLE['uuid']}"
    res = client.request(method, url, headers=employee_token(organisation_id=10, permissions=sorted(AGENT_PERMS)))
    lacks = not set(needed) <= AGENT_PERMS
    if lacks:
        assert res.status_code == 403, f"agent lacks {needed} but got {res.status_code}"
    else:
        assert res.status_code != 403, f"agent holds {needed} but was refused"
