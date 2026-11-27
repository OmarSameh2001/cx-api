"""Backend messages in every language (T1.10.5): catalogues stay complete,
every error the code raises has an entry, and responses come back in the
caller's language with a stable code."""

import ast
import string
from pathlib import Path

import pytest

from common import i18n
from common.errors import AppError
from common.i18n.locales import from_accept_language, normalize
from modules.auth import repository as auth_repo
from modules.audit import repository as audit_repo
from tests.conftest import employee_token

ROOT = Path(__file__).resolve().parents[1]
# routers switched off (E0.3): their messages never reach anyone
PARKED = ("keywords", "mentions", "mention_notification_deliveries", "mention_notification_rules",
          "tenants", "platform_configs")
ERRORS = {"HTTPException", "CodedHTTPException"}


def _placeholders(text: str) -> set[str]:
    return {field for _, field, _, _ in string.Formatter().parse(text) if field}


def _template(node) -> str | None:
    """A raised message as a template: f"Unit {unit_id} not found" -> "Unit {x} not found"."""
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        return "".join(
            v.value.replace("{", "{{").replace("}", "}}") if isinstance(v, ast.Constant) else "{x}"
            for v in node.values
        )
    return None


def _raised_messages():
    for path in sorted((ROOT / "modules").rglob("*.py")) + sorted((ROOT / "common").rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        if any(f"modules/{m}/" in rel for m in PARKED):
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            f = node.func
            name = f.id if isinstance(f, ast.Name) else f.attr if isinstance(f, ast.Attribute) else None
            detail = None
            if name in ERRORS:
                detail = next((kw.value for kw in node.keywords if kw.arg == "detail"), None)
                if detail is None:
                    detail = next((a for a in node.args if _template(a) is not None), None)
            elif name == "ValueError" and path.name == "dto.py" and node.args:
                detail = node.args[0]
            text = _template(detail) if detail is not None else None
            if text:
                yield f"{rel}:{node.lineno}", text


def _example(template: str) -> str:
    """The template with each placeholder filled, as the code would raise it."""
    return template.replace("{{", "\0").replace("}}", "\1").replace("{x}", "7").replace("\0", "{").replace("\1", "}")


def test_every_language_has_every_message_with_the_same_placeholders():
    english = i18n.entries("en")
    assert english, "no en catalogue"
    for code in i18n.LOCALES:
        other = i18n.entries(code)
        assert set(other) == set(english), f"{code}: missing {sorted(set(english) - set(other))}, extra {sorted(set(other) - set(english))}"
        for key, text in english.items():
            assert _placeholders(other[key]) == _placeholders(text), f"{code} {key}: placeholders differ"


def test_every_raised_error_message_has_a_catalogue_entry():
    missing = [f"{where}: {text!r}" for where, text in _raised_messages() if i18n.match(_example(text)) is None]
    assert not missing, "add these to common/i18n/messages/en (and every other language):\n" + "\n".join(missing)


# calls whose first string argument is a catalogue code (forms' fail() is its
# branching check's shorthand for AppError(422, code))
CODED = {"AppError": 1, "AuthError": 0, "fail": 0}


def _raised_codes():
    for path in sorted((ROOT / "modules").rglob("*.py")) + sorted((ROOT / "common").rglob("*.py")):
        rel = path.relative_to(ROOT).as_posix()
        if any(f"modules/{m}/" in rel for m in PARKED):
            continue
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) and node.func.id in CODED:
                index = CODED[node.func.id]
                arg = node.args[index] if len(node.args) > index else None
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    yield f"{rel}:{node.lineno}", arg.value, {k.arg for k in node.keywords} - {"headers", "status_code"}


def test_every_raised_code_is_in_the_catalogue_with_its_values():
    codes = i18n.catalogue.codes()
    english = i18n.entries("en")
    problems = []
    for where, code, params in _raised_codes():
        if code not in codes:
            problems.append(f"{where}: unknown code {code!r}")
        elif params != _placeholders(english[code]):
            problems.append(f"{where}: {code} takes {sorted(_placeholders(english[code]))}, given {sorted(params)}")
    assert not problems, "\n".join(problems)


def test_accept_language_picks_the_best_language_we_speak():
    assert from_accept_language("ar-EG,ar;q=0.9,en;q=0.8") == "ar"
    assert from_accept_language("fr-FR, ar;q=0.5, en;q=0.7") == "en"
    assert from_accept_language("fr, de") is None
    assert from_accept_language("en;q=0, ar;q=0.1") == "ar"
    assert normalize("AR_sa") == "ar" and normalize("xx") is None


def test_templates_with_values_are_matched_and_translated():
    code, text = i18n.translate_detail("Unit 42 not found", "ar")
    assert code == "units.id_not_found" and text == "الوحدة 42 غير موجودة"
    assert i18n.translate_detail("Unit 42 not found", "en") == ("units.id_not_found", "Unit 42 not found")
    assert i18n.translate_detail("something nobody wrote down", "ar") == (None, "something nobody wrote down")


def test_app_error_names_its_message_by_code():
    error = AppError(400, "files.too_large", limit=5)
    assert error.detail == "File is too large: the limit is 5 MB" and error.code == "files.too_large"


# ── through the app ───────────────────────────────────────────────────────────


def test_an_unknown_route_answers_in_arabic(client):
    res = client.get("/no-such-route", headers={**employee_token(), "Accept-Language": "ar"})
    assert res.status_code == 404
    assert res.json() == {"detail": "غير موجود", "error": "common.not_found"}
    assert res.headers["content-language"] == "ar"


def test_a_failed_sign_in_answers_in_the_callers_language(client, monkeypatch):
    monkeypatch.setattr(auth_repo, "get_employee_by_email", lambda db, email: None)
    monkeypatch.setattr(audit_repo, "count_failed_logins", lambda db, **kw: 0)
    body = {"email": "a@b.co", "password": "x"}
    ar = client.post("/auth/employee/login", json=body, headers={"Accept-Language": "ar"}).json()
    en = client.post("/auth/employee/login", json=body).json()
    assert ar == {"detail": "البريد الإلكتروني أو كلمة المرور غير صحيحة", "error": "auth.invalid_credentials"}
    assert en == {"detail": "Invalid email or password", "error": "auth.invalid_credentials"}


def test_the_auth_middleware_keeps_its_codes_and_translates_its_words(client):
    res = client.get("/roles", headers={"Accept-Language": "ar"})
    assert res.status_code == 401
    assert res.json() == {"error": "token_missing", "detail": "رمز الدخول غير موجود"}


def test_coded_errors_keep_their_code(client):
    res = client.get("/auth/sso/identities/1", headers={**employee_token(), "Accept-Language": "ar"})
    assert res.status_code in (404, 405)


def test_validation_errors_are_translated_and_never_echo_the_input(client):
    res = client.post("/auth/employee/login", json={"email": "not-an-email", "password": "hunter2"},
                      headers={"Accept-Language": "ar"})
    assert res.status_code == 422
    body = res.json()
    assert body["error"] == "validation.invalid_request"
    assert "hunter2" not in res.text and "input" not in body["detail"][0]
    assert body["detail"][0]["loc"] == ["body", "email"]

    res = client.post("/auth/employee/login", json={"email": "a@b.co"}, headers={"Accept-Language": "ar"})
    assert res.json()["detail"][0]["msg"] == "هذا الحقل مطلوب"


def test_english_validation_errors_keep_pydantics_wording(client):
    res = client.post("/auth/employee/login", json={"email": "a@b.co"})
    assert res.json()["detail"][0]["msg"] == "Field required"


def test_dto_value_errors_are_translated(client):
    res = client.put("/auth/me/preferences", json={"locale": "xx"}, headers=employee_token())
    assert res.status_code == 422


def test_saving_the_preferred_language(client, db, monkeypatch):
    from modules.employees.model import Employee

    me = Employee(id=1, organisation_id=10, is_active=True, preferred_locale=None)
    monkeypatch.setattr(auth_repo, "get_employee_by_id", lambda db, eid: me if eid == 1 else None)
    res = client.put("/auth/me/preferences", json={"locale": "ar"}, headers=employee_token())
    assert res.status_code == 200 and res.json() == {"locale": "ar"}
    assert me.preferred_locale == "ar" and db.commits == 1
    assert client.put("/auth/me/preferences", json={"locale": None}, headers=employee_token()).json() == {"locale": None}


@pytest.mark.parametrize("locale", sorted(i18n.LOCALES))
def test_every_language_has_a_name_and_direction(locale):
    entry = i18n.LOCALES[locale]
    assert entry.name and entry.direction in ("ltr", "rtl")
