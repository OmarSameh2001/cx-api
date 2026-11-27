"""Sign-in with Google and Microsoft (E1.11): the whole flow through the real
app against a fake provider whose ID tokens are signed with a test key, and
the ways someone might try to abuse it."""

import base64
import hashlib
import time
import uuid
from types import SimpleNamespace
from urllib.parse import parse_qs, urlparse

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from common.services import oidc
from common.services.oidc.providers import GoogleProvider, MicrosoftProvider
from config import SSOEnv
from modules.audit import repository as audit_repo
from modules.audit.model import AuditEvent
from modules.auth import repository as auth_repo
from modules.auth import service as auth_service
from modules.employees.model import Employee
from modules.organisations.model import Organisation
from modules.sso import repository as sso_repo
from modules.sso import service as sso_service
from modules.sso.model import UserIdentity
from tests.conftest import employee_token

KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
OTHER_KEY = rsa.generate_private_key(public_exponent=65537, key_size=2048)
CLIENT_ID = "client-123"
WORK_TENANT = "11111111-2222-3333-4444-555555555555"


class _Keys:
    def get_signing_key_from_jwt(self, token):
        return SimpleNamespace(key=KEY.public_key())


def _config(name):
    return oidc.ProviderConfig(name=name, client_id=CLIENT_ID, client_secret="secret",
                               discovery_url="https://idp.test/.well-known/openid-configuration",
                               label="", extra={})


class FakeMixin:
    """Answers like the real provider, from memory: the test sets the
    claims the next ID token carries."""

    issuer = "https://accounts.google.com"
    next_claims: dict = {}
    sign_with = KEY
    algorithm = "RS256"
    seen_verifiers: list

    def metadata(self):
        self._jwks = _Keys()
        return {
            "issuer": self.issuer,
            "authorization_endpoint": "https://idp.test/authorize",
            "token_endpoint": "https://idp.test/token",
            "jwks_uri": "https://idp.test/jwks",
            "id_token_signing_alg_values_supported": ["RS256"],
        }

    def exchange(self, *, code, redirect_uri, code_verifier):
        self.seen_verifiers.append((code, redirect_uri, code_verifier))
        if code == "bad":
            raise oidc.OIDCError("code_rejected")
        now = int(time.time())
        # Microsoft's issuer names the directory the token comes from
        issuer = self.issuer.replace("{tenantid}", str(self.next_claims.get("tid", "")))
        claims = {"iss": issuer, "aud": CLIENT_ID, "iat": now, "exp": now + 300, **self.next_claims}
        if self.algorithm == "HS256":
            return jwt.encode(claims, "secret", algorithm="HS256")
        if self.algorithm == "none":
            return jwt.encode(claims, None, algorithm="none")
        return jwt.encode(claims, self.sign_with, algorithm="RS256", headers={"kid": "k1"})


class FakeGoogle(FakeMixin, GoogleProvider):
    pass


class FakeMicrosoft(FakeMixin, MicrosoftProvider):
    issuer = "https://login.microsoftonline.com/{tenantid}/v2.0"


@pytest.fixture
def providers():
    google, microsoft = FakeGoogle(_config("google")), FakeMicrosoft(_config("microsoft"))
    google.name, microsoft.name = "google", "microsoft"
    google.seen_verifiers, microsoft.seen_verifiers = [], []
    oidc.reset_for_tests({"google": google, "microsoft": microsoft})
    yield SimpleNamespace(google=google, microsoft=microsoft)
    oidc.reset_for_tests(None)


@pytest.fixture
def world(monkeypatch, db):
    """Two organisations' worth of employees and identities, in memory."""
    org = Organisation(id=10, name="Acme", sign_in_settings={})
    sara = Employee(id=3, organisation_id=10, email="Sara@Acme.com", is_active=True, first_name="Sara",
                    last_name="Ali", password=auth_service.hash_password("right"), role_id=None, unit_id=None,
                    is_platform_admin=False, refresh_tokens=[], preferred_locale=None)
    boss = Employee(id=4, organisation_id=10, email="boss@acme.com", is_active=True, first_name="B",
                    last_name="C", password=auth_service.hash_password("right"), role_id=None, unit_id=None,
                    is_platform_admin=True, refresh_tokens=[], preferred_locale=None)
    state = SimpleNamespace(org=org, employees={3: sara, 4: boss}, identities=[], notified=[])

    monkeypatch.setattr(sso_repo, "get_organisation", lambda db, oid: org if oid == 10 else None)
    monkeypatch.setattr(sso_repo, "get_employee", lambda db, eid: state.employees.get(eid))
    monkeypatch.setattr(sso_repo, "employees_with_email",
                        lambda db, email: [e for e in state.employees.values() if e.email.lower() == email.lower()][:2])
    monkeypatch.setattr(sso_repo, "get_identity", lambda db, p, s: next(
        (i for i in state.identities if i.provider == p and i.subject == s), None))
    monkeypatch.setattr(sso_repo, "identity_of", lambda db, eid, p: next(
        (i for i in state.identities if i.employee_id == eid and i.provider == p), None))
    monkeypatch.setattr(sso_repo, "identities_of", lambda db, eid: [i for i in state.identities if i.employee_id == eid])
    monkeypatch.setattr(sso_repo, "get_owned_identity", lambda db, eid, iid: next(
        (i for i in state.identities if i.employee_id == eid and i.id == iid), None))

    def add_identity(db, row):
        row.id = len(state.identities) + 1
        state.identities.append(row)
        return row

    monkeypatch.setattr(sso_repo, "add_identity", add_identity)
    monkeypatch.setattr(sso_repo, "delete_identity", lambda db, row: state.identities.remove(row))
    monkeypatch.setattr(auth_repo, "get_employee_by_id", lambda db, eid: state.employees.get(eid))
    monkeypatch.setattr(auth_repo, "add_refresh_jti", lambda db, *a: db.commit())
    monkeypatch.setattr(audit_repo, "count_failed_logins", lambda db, **kw: 0)
    monkeypatch.setattr(sso_service, "notify_owner",
                        lambda db, employee, template, **p: state.notified.append((employee.id, template)))
    return state


def audit_events(db, action=None):
    return [o for o in db.added if isinstance(o, AuditEvent) and (action is None or o.action == action)]


def begin(client, provider="google", next_path="/forms/7", **params):
    query = {"next": next_path, **params}
    res = client.get(f"/auth/sso/{provider}/start", params=query, follow_redirects=False)
    assert res.status_code == 303, res.text
    location = urlparse(res.headers["location"])
    return res, {k: v[0] for k, v in parse_qs(location.query).items()}


def finish(client, provider="google", **query):
    return client.get(f"/auth/sso/{provider}/callback", params=query, follow_redirects=False)


def where(res):
    url = urlparse(res.headers["location"])
    return url.path, {k: v[0] for k, v in parse_qs(url.query).items()}


def google_claims(**over):
    return {"sub": "g-sara", "email": "sara@acme.com", "email_verified": True, **over}


# ── the happy path ────────────────────────────────────────────────────────────


def test_providers_lists_only_switched_on_ones(client, providers):
    res = client.get("/auth/sso/providers")
    assert res.status_code == 200
    assert res.json() == {"providers": [{"name": "google", "label": "Google"}, {"name": "microsoft", "label": "Microsoft"}]}


def test_start_sends_the_browser_to_the_provider_with_pkce_state_and_nonce(client, providers):
    res, q = begin(client)
    assert res.headers["location"].startswith("https://idp.test/authorize?")
    assert q["client_id"] == CLIENT_ID and q["response_type"] == "code"
    assert q["redirect_uri"] == f"{SSOEnv.SSO_CALLBACK_BASE_URL}/auth/sso/google/callback"
    assert q["code_challenge_method"] == "S256" and len(q["state"]) >= 32 and len(q["nonce"]) >= 32
    cookie = res.headers["set-cookie"]
    assert "sso_flow=" in cookie and "HttpOnly" in cookie and "Path=/auth/sso" in cookie
    assert "samesite=lax" in cookie.lower()
    assert res.headers["cache-control"] == "no-store"


def test_a_verified_google_account_signs_in_and_links_by_email(client, db, providers, world):
    _, q = begin(client)
    providers.google.next_claims = google_claims(nonce=q["nonce"])
    res = finish(client, code="good", state=q["state"])
    assert res.status_code == 303
    assert where(res) == ("/sso/complete", {"next": "/forms/7"})
    cookies = res.headers.get_list("set-cookie")
    assert any(c.startswith("access_token=") for c in cookies)
    assert any(c.startswith("refresh_token=") for c in cookies)
    # the flow cookie is gone: the callback can't be used twice
    assert any(c.startswith("sso_flow=") and "Max-Age=0" in c for c in cookies)
    assert res.headers["referrer-policy"] == "no-referrer"

    # PKCE: the verifier sent to the token endpoint matches the challenge
    code, redirect, verifier = providers.google.seen_verifiers[0]
    assert (code, redirect) == ("good", f"{SSOEnv.SSO_CALLBACK_BASE_URL}/auth/sso/google/callback")

    [identity] = world.identities
    assert (identity.employee_id, identity.provider, identity.subject) == (3, "google", "g-sara")
    assert [e.action for e in audit_events(db)] == ["auth.identity_linked", "auth.login"]
    assert audit_events(db, "auth.login")[0].data == {"method": "google"}
    assert world.notified == [(3, "security.identity_linked")]


def test_the_pkce_challenge_is_the_hash_of_the_verifier(client, providers, world):
    _, q = begin(client)
    providers.google.next_claims = google_claims(nonce=q["nonce"])
    finish(client, code="good", state=q["state"])
    verifier = providers.google.seen_verifiers[0][2]
    expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    assert q["code_challenge"] == expected


def test_a_linked_account_signs_in_by_its_subject_even_after_an_email_change(client, db, providers, world):
    world.identities.append(UserIdentity(id=1, organisation_id=10, employee_id=3, provider="google",
                                         subject="g-sara", email="sara@acme.com"))
    _, q = begin(client)
    # the Google address changed and isn't verified: the stable id still matches
    providers.google.next_claims = google_claims(nonce=q["nonce"], email="new@else.com", email_verified=False)
    res = finish(client, code="good", state=q["state"])
    assert where(res)[0] == "/sso/complete"
    assert world.identities[0].last_used_at is not None
    assert world.notified == []


def test_the_session_endpoint_returns_the_signed_in_employee(client, world, monkeypatch):
    monkeypatch.setattr(auth_repo, "get_role_claims", lambda db, rid: None)
    res = client.get("/auth/session", headers=employee_token(id=3))
    assert res.status_code == 200, res.text
    assert res.json()["user"]["id"] == 3 and res.json()["user"]["organisation_id"] == 10


# ── forged, replayed and stolen callbacks ───────────────────────────────────────


def test_a_callback_without_the_flow_cookie_is_refused(client, db, providers, world):
    _, q = begin(client)
    providers.google.next_claims = google_claims(nonce=q["nonce"])
    client.cookies.clear()  # another browser: the link was sent to someone
    res = finish(client, code="good", state=q["state"])
    assert where(res) == ("/login", {"sso_error": "expired"})
    assert providers.google.seen_verifiers == []  # never even swapped the code
    assert audit_events(db, "auth.login_failed")[0].data == {"reason": "no_flow", "method": "google"}


def test_a_wrong_state_is_refused(client, db, providers, world):
    _, q = begin(client)
    providers.google.next_claims = google_claims(nonce=q["nonce"])
    res = finish(client, code="good", state="x" * 43)
    assert where(res) == ("/login", {"sso_error": "failed"})
    assert providers.google.seen_verifiers == [] and world.identities == []
    assert audit_events(db, "auth.login_failed")[0].data["reason"] == "state_mismatch"


def test_a_forged_flow_cookie_is_refused(client, providers, world):
    begin(client)
    forged = jwt.encode({"typ": "sso_flow", "provider": "google", "state": "s", "nonce": "n", "verifier": "v",
                         "mode": "login", "iat": int(time.time()), "exp": int(time.time()) + 60, "iss": "cx-api"},
                        "not-our-secret", algorithm="HS256")
    client.cookies.set("sso_flow", forged, path="/auth/sso")
    res = finish(client, code="good", state="s")
    assert where(res) == ("/login", {"sso_error": "expired"})


def test_a_replayed_callback_fails(client, providers, world):
    _, q = begin(client)
    providers.google.next_claims = google_claims(nonce=q["nonce"])
    assert where(finish(client, code="good", state=q["state"]))[0] == "/sso/complete"
    # the browser no longer holds the flow cookie
    assert where(finish(client, code="good", state=q["state"]))[1] == {"sso_error": "expired"}


def test_a_flow_started_for_one_provider_cant_finish_at_another(client, providers, world):
    _, q = begin(client, "google")
    res = finish(client, "microsoft", code="good", state=q["state"])
    assert where(res) == ("/login", {"sso_error": "expired"})


def test_cancelling_at_the_provider_says_so(client, providers, world):
    _, q = begin(client)
    res = finish(client, error="access_denied", state=q["state"])
    assert where(res) == ("/login", {"sso_error": "cancelled"})


def test_a_code_the_provider_rejects_fails(client, providers, world):
    _, q = begin(client)
    res = finish(client, code="bad", state=q["state"])
    assert where(res) == ("/login", {"sso_error": "failed"})


# ── ID tokens that must not be trusted ─────────────────────────────────────────


@pytest.mark.parametrize("change", [
    {"nonce": "someone-elses-nonce"},
    {"aud": "another-client"},
    {"iss": "https://evil.example"},
    {"exp": int(time.time()) - 3600},
    {"iat": int(time.time()) - 3600, "exp": int(time.time()) + 300},
    {"aud": [CLIENT_ID, "other"], "azp": "other"},
])
def test_a_bad_id_token_is_refused(client, db, providers, world, change):
    _, q = begin(client)
    providers.google.next_claims = {**google_claims(nonce=q["nonce"]), **change}
    res = finish(client, code="good", state=q["state"])
    assert where(res) == ("/login", {"sso_error": "failed"})
    assert world.identities == [] and audit_events(db, "auth.login") == []
    assert audit_events(db, "auth.login_failed")[0].data["reason"] == "bad_token"


@pytest.mark.parametrize("trick", ["other_key", "HS256", "none"])
def test_a_token_not_signed_by_the_provider_is_refused(client, providers, world, trick):
    _, q = begin(client)
    providers.google.next_claims = google_claims(nonce=q["nonce"])
    if trick == "other_key":
        providers.google.sign_with = OTHER_KEY
    else:
        providers.google.algorithm = trick
    res = finish(client, code="good", state=q["state"])
    assert where(res) == ("/login", {"sso_error": "failed"})
    assert world.identities == []


# ── who may sign in ───────────────────────────────────────────────────────────


def _sign_in(client, providers, provider="google", **claims):
    _, q = begin(client, provider)
    getattr(providers, provider).next_claims = {**claims, "nonce": q["nonce"]}
    return where(finish(client, provider, code="good", state=q["state"]))


def test_an_unverified_google_email_is_refused(client, db, providers, world):
    assert _sign_in(client, providers, **google_claims(email_verified=False)) == ("/login", {"sso_error": "failed"})
    assert world.identities == []
    [event] = audit_events(db, "auth.login_failed")
    assert event.data["reason"] == "email_not_verified" and event.entity_id == 3


def test_an_unknown_email_gets_the_same_answer_as_any_other_refusal(client, db, providers, world):
    assert _sign_in(client, providers, **google_claims(email="nobody@acme.com")) == ("/login", {"sso_error": "failed"})
    [event] = audit_events(db, "auth.login_failed")
    assert event.data["reason"] == "unknown_account" and event.entity_id is None
    assert "nobody" not in repr(vars(event))


def test_a_disabled_employee_cant_sign_in(client, db, providers, world):
    world.employees[3].is_active = False
    assert _sign_in(client, providers, **google_claims()) == ("/login", {"sso_error": "failed"})
    assert world.identities == []
    assert audit_events(db, "auth.login_blocked")[0].data == {"method": "google"}


def test_a_platform_admin_is_never_linked_by_email(client, db, providers, world):
    assert _sign_in(client, providers, **google_claims(sub="g-boss", email="boss@acme.com")) == \
        ("/login", {"sso_error": "failed"})
    assert world.identities == []
    assert audit_events(db, "auth.login_failed")[0].data["reason"] == "platform_admin_must_link"


def test_an_email_match_cant_add_a_second_account_of_the_same_provider(client, db, providers, world):
    world.identities.append(UserIdentity(id=1, organisation_id=10, employee_id=3, provider="google",
                                         subject="g-original", email="sara@acme.com"))
    assert _sign_in(client, providers, **google_claims(sub="g-attacker")) == ("/login", {"sso_error": "failed"})
    assert len(world.identities) == 1
    assert audit_events(db, "auth.login_failed")[0].data["reason"] == "other_account_linked"


def test_microsoft_personal_accounts_are_verified(client, providers, world):
    claims = {"sub": "x", "tid": oidc.MICROSOFT_CONSUMER_TENANT, "oid": "o-1", "email": "sara@acme.com"}
    assert _sign_in(client, providers, "microsoft", **claims)[0] == "/sso/complete"
    [identity] = world.identities
    assert identity.subject == f"{oidc.MICROSOFT_CONSUMER_TENANT}:o-1"


def test_a_microsoft_work_email_set_by_any_directory_is_not_trusted(client, db, providers, world):
    """nOAuth: an attacker's own directory can put any address in `email`."""
    claims = {"sub": "x", "tid": WORK_TENANT, "oid": "o-evil", "email": "sara@acme.com"}
    assert _sign_in(client, providers, "microsoft", **claims) == ("/login", {"sso_error": "failed"})
    assert world.identities == []
    assert audit_events(db, "auth.login_failed")[0].data["reason"] == "email_not_verified"


def test_a_microsoft_work_email_counts_when_microsoft_verified_the_domain(client, providers, world):
    claims = {"sub": "x", "tid": WORK_TENANT, "oid": "o-1", "email": "sara@acme.com", "xms_edov": True}
    assert _sign_in(client, providers, "microsoft", **claims)[0] == "/sso/complete"


def test_a_trusted_directory_makes_its_emails_count(client, providers, world):
    world.org.sign_in_settings = {"trusted_microsoft_tenants": [WORK_TENANT]}
    claims = {"sub": "x", "tid": WORK_TENANT, "oid": "o-1", "email": "sara@acme.com"}
    assert _sign_in(client, providers, "microsoft", **claims)[0] == "/sso/complete"


def test_trusted_directories_also_keep_other_work_directories_out(client, db, providers, world):
    world.org.sign_in_settings = {"trusted_microsoft_tenants": [WORK_TENANT]}
    other = "99999999-2222-3333-4444-555555555555"
    claims = {"sub": "x", "tid": other, "oid": "o-1", "email": "sara@acme.com", "xms_edov": True}
    assert _sign_in(client, providers, "microsoft", **claims) == ("/login", {"sso_error": "failed"})
    assert audit_events(db, "auth.login_failed")[0].data["reason"] == "tenant_not_trusted"


def test_a_microsoft_token_from_another_directory_issuer_is_refused(client, providers, world):
    _, q = begin(client, "microsoft")
    providers.microsoft.next_claims = {"sub": "x", "tid": WORK_TENANT, "oid": "o", "email": "sara@acme.com",
                                       "xms_edov": True, "nonce": q["nonce"],
                                       "iss": "https://login.microsoftonline.com/99999999-2222-3333-4444-555555555555/v2.0"}
    assert where(finish(client, "microsoft", code="good", state=q["state"])) == ("/login", {"sso_error": "failed"})


@pytest.mark.parametrize("settings, claims, reason", [
    ({"providers": {"google": {"enabled": False}}}, {}, "provider_disabled_for_organisation"),
    ({"allow_personal_accounts": False}, {}, "personal_account_not_allowed"),
    ({"allowed_email_domains": ["other.com"]}, {}, "email_domain_not_allowed"),
    ({"link_by_email": False}, {}, "link_by_email_disabled"),
])
def test_organisation_settings_are_enforced(client, db, providers, world, settings, claims, reason):
    world.org.sign_in_settings = settings
    assert _sign_in(client, providers, **google_claims(**claims)) == ("/login", {"sso_error": "failed"})
    assert world.identities == []
    assert audit_events(db, "auth.login_failed")[0].data["reason"] == reason


def test_workspace_accounts_pass_when_personal_ones_are_off(client, providers, world):
    world.org.sign_in_settings = {"allow_personal_accounts": False, "allowed_email_domains": ["acme.com"]}
    assert _sign_in(client, providers, **google_claims(hd="acme.com"))[0] == "/sso/complete"


# ── where people land afterwards ─────────────────────────────────────────────────


@pytest.mark.parametrize("evil", ["//evil.example", "https://evil.example", "/\\evil.example",
                                  "/login?x=1", "evil", "/ok\r\nSet-Cookie: a=b"])
def test_next_never_leaves_the_app(client, providers, world, evil):
    _, q = begin(client, next_path=evil)
    providers.google.next_claims = google_claims(nonce=q["nonce"])
    res = finish(client, code="good", state=q["state"])
    assert where(res) == ("/sso/complete", {"next": "/"})
    assert res.headers["location"].startswith(SSOEnv.SSO_APP_URL + "/")


def test_an_unknown_provider_goes_back_to_the_login_page(client, providers):
    res = client.get("/auth/sso/github/start", follow_redirects=False)
    assert where(res) == ("/login", {"sso_error": "unavailable"})


def test_start_is_rate_limited_per_ip(client, providers, monkeypatch):
    monkeypatch.setattr(SSOEnv, "SSO_STARTS_PER_MINUTE_PER_IP", 2)
    begin(client), begin(client)
    res = client.get("/auth/sso/google/start", follow_redirects=False)
    assert where(res) == ("/login", {"sso_error": "rate_limited"})


# ── linking from the profile ────────────────────────────────────────────────────


def _ticket_url(client, password="right", provider="google"):
    return client.post(f"/auth/sso/{provider}/link", json={"password": password}, headers=employee_token(id=3))


def _signed_in_browser(client, employee_id=3):
    token = employee_token(id=employee_id)["Authorization"].split(" ", 1)[1]
    client.cookies.set("access_token", token)


def test_linking_needs_the_password(client, db, providers, world):
    res = _ticket_url(client, password="wrong")
    assert res.status_code == 403 and res.json()["error"] == "auth.wrong_password"
    assert audit_events(db, "auth.login_failed")[0].data == {"reason": "wrong_password", "method": "link:google"}


def test_linking_from_the_profile(client, db, providers, world):
    world.employees[4].is_platform_admin = True
    res = client.post("/auth/sso/google/link", json={"password": "right"}, headers=employee_token(id=4))
    assert res.status_code == 200, res.text
    _signed_in_browser(client, 4)
    start_url = urlparse(res.json()["url"])
    res = client.get(start_url.path + "?" + start_url.query, follow_redirects=False)
    q = {k: v[0] for k, v in parse_qs(urlparse(res.headers["location"]).query).items()}
    # the Google address doesn't even need to match: the password proved who it is
    providers.google.next_claims = {"sub": "g-boss", "email": "boss.personal@gmail.com", "email_verified": False,
                                    "nonce": q["nonce"]}
    res = finish(client, code="good", state=q["state"])
    assert where(res) == ("/profile", {"sso_linked": "google"})
    [identity] = world.identities
    assert identity.employee_id == 4
    # linking doesn't sign anyone in
    assert not any(c.startswith("access_token=") for c in res.headers.get_list("set-cookie"))
    assert world.notified == [(4, "security.identity_linked")]


def test_a_stolen_link_ticket_is_useless_in_another_browser(client, providers, world):
    url = urlparse(_ticket_url(client).json()["url"])
    # no access cookie (another browser), or someone else's
    res = client.get(url.path + "?" + url.query, follow_redirects=False)
    assert where(res) == ("/profile", {"sso_error": "link_failed"})
    _signed_in_browser(client, 4)
    res = client.get(url.path + "?" + url.query, follow_redirects=False)
    assert where(res) == ("/profile", {"sso_error": "link_failed"})


def test_a_link_ticket_works_once(client, providers, world):
    url = urlparse(_ticket_url(client).json()["url"])
    _signed_in_browser(client)
    assert urlparse(client.get(url.path + "?" + url.query, follow_redirects=False).headers["location"]).netloc == "idp.test"
    assert where(client.get(url.path + "?" + url.query, follow_redirects=False)) == ("/profile", {"sso_error": "link_failed"})


def test_an_account_linked_to_someone_else_cant_be_linked_again(client, providers, world):
    world.identities.append(UserIdentity(id=1, organisation_id=10, employee_id=4, provider="google",
                                         subject="g-taken", email="x@y.com"))
    url = urlparse(_ticket_url(client).json()["url"])
    _signed_in_browser(client)
    res = client.get(url.path + "?" + url.query, follow_redirects=False)
    q = {k: v[0] for k, v in parse_qs(urlparse(res.headers["location"]).query).items()}
    providers.google.next_claims = {"sub": "g-taken", "email": "x@y.com", "email_verified": True, "nonce": q["nonce"]}
    assert where(finish(client, code="good", state=q["state"])) == ("/profile", {"sso_error": "in_use"})


def test_linking_a_second_account_of_one_provider_is_refused(client, providers, world):
    world.identities.append(UserIdentity(id=1, organisation_id=10, employee_id=3, provider="google",
                                         subject="g-sara", email="sara@acme.com"))
    res = _ticket_url(client)
    assert res.status_code == 409 and res.json()["error"] == "sso.already_linked"


def test_listing_and_removing_my_accounts(client, db, providers, world):
    world.identities.append(UserIdentity(id=1, organisation_id=10, employee_id=3, provider="google",
                                         subject="g-sara", email="sara@acme.com", created_at=sso_service._now()))
    world.identities.append(UserIdentity(id=2, organisation_id=10, employee_id=4, provider="google",
                                         subject="g-boss", email="boss@acme.com", created_at=sso_service._now()))
    res = client.get("/auth/sso/identities", headers=employee_token(id=3))
    assert [(i["id"], i["label"], i["email"]) for i in res.json()] == [(1, "Google", "sara@acme.com")]
    # someone else's: not found, not removed
    assert client.delete("/auth/sso/identities/2", headers=employee_token(id=3)).status_code == 404
    assert client.delete("/auth/sso/identities/1", headers=employee_token(id=3)).status_code == 204
    assert [i.id for i in world.identities] == [2]
    assert audit_events(db, "auth.identity_unlinked")[0].data == {"method": "google"}
    assert world.notified == [(3, "security.identity_unlinked")]


def test_identity_endpoints_need_a_session(client, providers):
    assert client.get("/auth/sso/identities").status_code == 401
    assert client.post("/auth/sso/google/link", json={"password": "x"}).status_code == 401


# ── organisation settings ───────────────────────────────────────────────────────


def test_only_admins_see_or_change_sign_in_settings(client, providers, world):
    assert client.get("/auth/sso/settings", headers=employee_token(id=3)).status_code == 403
    assert client.put("/auth/sso/settings", json={}, headers=employee_token(id=3)).status_code == 403


def test_admins_change_sign_in_settings(client, db, providers, world):
    body = {"providers": {"microsoft": {"enabled": False}}, "allow_personal_accounts": False,
            "allowed_email_domains": ["@Acme.com", "acme.com"], "trusted_microsoft_tenants": [WORK_TENANT.upper()]}
    res = client.put("/auth/sso/settings", json=body, headers=employee_token(id=3, is_admin=True))
    assert res.status_code == 200, res.text
    saved = world.org.sign_in_settings
    assert saved["allowed_email_domains"] == ["acme.com"] and saved["trusted_microsoft_tenants"] == [WORK_TENANT]
    assert res.json()["available_providers"][0]["name"] == "google"
    assert audit_events(db, "organisation.sign_in_settings_changed")[0].organisation_id == 10


@pytest.mark.parametrize("body", [
    {"allowed_email_domains": ["not a domain"]},
    {"trusted_microsoft_tenants": ["not-a-uuid"]},
    {"unknown": True},
])
def test_bad_sign_in_settings_are_refused(client, providers, world, body):
    res = client.put("/auth/sso/settings", json=body, headers=employee_token(id=3, is_admin=True))
    assert res.status_code == 422


# ── password sign-in hardening ────────────────────────────────────────────────


def test_wrong_passwords_lock_the_account_for_a_while(client, world, monkeypatch):
    monkeypatch.setattr(auth_repo, "get_employee_by_email",
                        lambda db, email: world.employees[3] if email == "sara@acme.com" else None)
    monkeypatch.setattr(auth_repo, "get_role_claims", lambda db, rid: None)
    monkeypatch.setattr(SSOEnv, "LOGIN_FAILURES_PER_EMAIL", 3)

    def login(password):
        return client.post("/auth/employee/login",
                           json={"email": "sara@acme.com", "password": password}).status_code

    # signing in successfully, however often, never counts
    assert [login("right") for _ in range(5)] == [200] * 5
    assert [login("wrong") for _ in range(3)] == [401] * 3
    # now even the right password waits: guessing can't continue
    res = client.post("/auth/employee/login", json={"email": "sara@acme.com", "password": "right"})
    assert res.status_code == 429 and int(res.headers["retry-after"]) > 0
    # other accounts aren't affected
    assert client.post("/auth/employee/login", json={"email": "x@acme.com", "password": "x"}).status_code == 401


def test_password_sign_in_is_rate_limited_per_ip(client, world, monkeypatch):
    monkeypatch.setattr(auth_repo, "get_employee_by_email", lambda db, email: None)
    monkeypatch.setattr(SSOEnv, "LOGINS_PER_MINUTE_PER_IP", 2)
    codes = [client.post("/auth/employee/login", json={"email": f"{i}@acme.com", "password": "x"}).status_code
             for i in range(3)]
    assert codes == [401, 401, 429]


def test_an_unknown_email_takes_as_long_as_a_wrong_password(client, world, monkeypatch):
    calls = []
    real = auth_service.verify_password
    monkeypatch.setattr(auth_service, "verify_password", lambda p, h: calls.append(h) or real(p, h))
    monkeypatch.setattr(auth_repo, "get_employee_by_email", lambda db, email: None)
    client.post("/auth/employee/login", json={"email": "nobody@acme.com", "password": "x"})
    assert len(calls) == 1  # a bcrypt check ran even with no account
