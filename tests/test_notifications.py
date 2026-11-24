"""E1.9 notifications: templates in both languages, notifying, sending with
retries, the provider registry and fallback, and the bell's endpoints."""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
import requests

from common.services import messaging
from common.services.messaging import registry
from common.services.messaging.base import ConfigError, Message, MessagingError, Provider, ProviderConfig, SendResult
from config import NotificationsEnv
from modules.notifications import repository as repo
from modules.notifications import service, templates
from modules.notifications.model import Notification, NotificationDelivery
from tests.conftest import employee_token

PEOPLE = {
    2: SimpleNamespace(id=2, email="sara@x.co", phone="+201001234567"),
    3: SimpleNamespace(id=3, email=None, phone=None),
}


@pytest.fixture(autouse=True)
def channels_off(monkeypatch):
    for channel in ("EMAIL", "SMS", "WHATSAPP", "SLACK"):
        monkeypatch.delenv(f"{channel}_PROVIDERS", raising=False)
    registry.reset_for_tests()
    yield
    registry.reset_for_tests()


@pytest.fixture
def people(monkeypatch):
    monkeypatch.setattr(repo, "recipients", lambda db, *, organisation_id, employee_ids: [
        PEOPLE[i] for i in employee_ids if i in PEOPLE and organisation_id == 10
    ])
    return PEOPLE


def added(db, cls):
    return [o for o in db.added if isinstance(o, cls)]


# ── templates ────────────────────────────────────────────────────────────────

def test_templates_render_in_english_and_arabic():
    params = {"task": "Call back", "due": "Thursday"}
    assert templates.render("task.assigned", params, "en").title == "New task: Call back"
    assert templates.render("task.assigned", params, "ar").title == "مهمة جديدة: Call back"


def test_every_template_has_both_languages_and_only_simple_placeholders():
    for key, texts in templates.TEMPLATES.items():
        assert set(texts) == set(templates.LOCALES), key
        for text in texts.values():
            templates.render(key, {}, "en")  # raises on {a.b} or {a[0]}
            assert "{" not in templates.render(key, {}, "en").title


def test_a_missing_parameter_renders_as_nothing_and_channels_are_named_per_language():
    assert templates.render("system.test", {"app": "CX", "channel": "sms"}, "en").body.endswith("SMS notifications work.")
    assert "الرسائل النصية" in templates.render("system.test", {"app": "CX", "channel": "sms"}, "ar").body
    assert templates.render("form.assigned", {"form": "Survey"}, "en").body == "Survey was assigned to you. Please answer it by ."


def test_placeholders_cannot_reach_into_objects():
    with pytest.raises(ValueError):
        templates._fill("{p.__class__}", {"p": 1})


def test_locales_fall_back_to_the_default():
    assert templates.locale_or_default("ar-EG", "en") == "ar"
    assert templates.locale_or_default("fr", "en") == "en"
    assert templates.locale_or_default(None, "ar") == "ar"


def test_arabic_email_is_right_to_left_and_parameters_are_escaped():
    text = templates.render("system.message", {"title": "<b>x</b>", "body": "a & b"}, "ar")
    html = templates.email_html(text, locale="ar", link="https://app/x?a=1&b=2", app_name="CX")
    assert 'dir="rtl"' in html and "&lt;b&gt;x&lt;/b&gt;" in html and "a &amp; b" in html
    assert "<b>x</b>" not in html and 'href="https://app/x?a=1&amp;b=2"' in html


# ── notifying ─────────────────────────────────────────────────────────────────

def test_notify_adds_one_in_app_row_per_active_person_of_the_organisation(db, people):
    notes, deliveries = service.notify(db, organisation_id=10, recipient_ids=[2, 3, 99], template="task.assigned",
                                       params={"task": "T"}, link="/tasks/1")
    assert [n.recipient_id for n in notes] == [2, 3] and deliveries == []
    assert all(n.template == "task.assigned" and n.link == "/tasks/1" for n in added(db, Notification))


def test_channels_without_a_provider_queue_nothing(db, people):
    _, deliveries = service.notify(db, organisation_id=10, recipient_ids=[2], template="task.assigned",
                                   channels=["in_app", "email", "sms"])
    assert deliveries == []


def test_deliveries_go_to_people_with_an_address_and_slack_once(db, people, monkeypatch):
    for channel in ("EMAIL", "SMS", "SLACK"):
        monkeypatch.setenv(f"{channel}_PROVIDERS", "log")
    notes, deliveries = service.notify(
        db, organisation_id=10, recipient_ids=[2, 3], template="task.assigned",
        channels=["in_app", "email", "sms", "slack"], locale="ar",
    )
    got = sorted((d.channel, d.address, d.recipient_id) for d in deliveries)
    assert got == [("email", "sara@x.co", 2), ("slack", "", None), ("sms", "+201001234567", 2)]
    by_person = {n.recipient_id: n.id for n in notes}
    assert all(d.notification_id == by_person[2] for d in deliveries if d.recipient_id == 2)
    assert {d.locale for d in deliveries} == {"ar"} and {d.status for d in deliveries} == {"pending"}


def test_unknown_templates_and_channels_are_refused(db, people):
    with pytest.raises(ValueError, match="template"):
        service.notify(db, organisation_id=10, recipient_ids=[2], template="nope")
    with pytest.raises(ValueError, match="channels"):
        service.notify(db, organisation_id=10, recipient_ids=[2], template="task.assigned", channels=["fax"])


# ── sending and retrying ──────────────────────────────────────────────────────

def delivery(**kw):
    data = dict(id=7, organisation_id=10, channel="email", address="sara@x.co", template="task.assigned",
                params={"task": "T", "due": "Thu"}, link="/tasks/1", locale="en", status="sending", attempts=1,
                next_attempt_at=datetime.now(timezone.utc))
    data.update(kw)
    return NotificationDelivery(**data)


def test_an_email_message_has_subject_text_html_and_an_absolute_link(monkeypatch):
    monkeypatch.setattr(NotificationsEnv, "APP_URL", "https://cx.example")
    message = service.message_for(delivery())
    assert message.subject == "New task: T" and message.reference == "delivery-7"
    assert "https://cx.example/tasks/1" in message.text and "https://cx.example/tasks/1" in message.html


def test_a_sent_delivery_records_the_provider(monkeypatch):
    monkeypatch.setattr(messaging, "send", lambda m: SendResult("resend", "abc"))
    row = delivery()
    service.send_one(row)
    assert (row.status, row.provider, row.provider_message_id, row.last_error) == ("sent", "resend", "abc", None)
    assert row.sent_at is not None


def test_a_transient_failure_is_retried_later_with_backoff(monkeypatch):
    def down(message):
        raise MessagingError("resend: HTTP 503", provider="resend")

    monkeypatch.setattr(messaging, "send", down)
    row = delivery(attempts=2)
    before = datetime.now(timezone.utc)
    service.send_one(row)
    assert row.status == "pending" and "503" in row.last_error
    assert row.next_attempt_at >= before + timedelta(seconds=119)


def test_a_permanent_failure_or_the_last_attempt_fails_for_good(monkeypatch):
    def refused(message):
        raise MessagingError("bad address", permanent=True, provider="smtp")

    monkeypatch.setattr(messaging, "send", refused)
    row = delivery()
    service.send_one(row)
    assert row.status == "failed"

    monkeypatch.setattr(messaging, "send", lambda m: (_ for _ in ()).throw(MessagingError("timeout")))
    row = delivery(attempts=NotificationsEnv.NOTIFICATIONS_MAX_ATTEMPTS)
    service.send_one(row)
    assert row.status == "failed"


def test_the_worker_commits_its_claim_then_each_result(db, monkeypatch):
    rows = [delivery(id=1), delivery(id=2)]
    monkeypatch.setattr(repo, "claim_due", lambda db, **kw: rows)
    outcomes = iter([SendResult("log"), MessagingError("down")])

    def send(message):
        outcome = next(outcomes)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    monkeypatch.setattr(messaging, "send", send)
    assert service.deliver_due(db) == {"sent": 1, "failed": 0, "retrying": 1}
    assert db.commits == 3


# ── the provider registry ─────────────────────────────────────────────────────

class Flaky(Provider):
    calls: list = []

    def send(self, message):
        Flaky.calls.append(self.name)
        behaviour = self.config.get("BEHAVIOUR")
        if behaviour == "down":
            raise MessagingError(f"{self.name} down")
        if behaviour == "refuse":
            raise MessagingError(f"{self.name} refused", permanent=True)
        if behaviour == "unset":
            raise ConfigError(f"{self.name.upper()}_KEY must be set")
        return SendResult(self.name, "ok")


@pytest.fixture
def flaky(monkeypatch):
    Flaky.calls = []
    for name in ("first", "second"):
        cls = type(name.title(), (Flaky,), {})
        monkeypatch.setitem(registry._classes, ("email", name), registry.provider("email", name)(cls))
    return Flaky


def email(to="a@b.co"):
    return Message(channel="email", to=to, text="hi")


@pytest.mark.parametrize("first, expected_calls, ok", [
    ("ok", ["first"], True),
    ("down", ["first", "second"], True),       # down: the next provider takes it
    ("unset", ["first", "second"], True),      # not configured: the next one too
    ("refuse", ["first"], False),              # the message itself was refused: stop
])
def test_providers_are_tried_in_order(flaky, monkeypatch, first, expected_calls, ok):
    monkeypatch.setenv("EMAIL_PROVIDERS", "first, second")
    monkeypatch.setenv("FIRST_BEHAVIOUR", first)
    monkeypatch.delenv("SECOND_BEHAVIOUR", raising=False)
    if ok:
        assert messaging.send(email()).provider == ("first" if first == "ok" else "second")
    else:
        with pytest.raises(MessagingError) as exc:
            messaging.send(email())
        assert exc.value.permanent
    assert flaky.calls == expected_calls


def test_when_every_provider_is_down_the_error_can_be_retried(flaky, monkeypatch):
    monkeypatch.setenv("EMAIL_PROVIDERS", "first,second")
    monkeypatch.setenv("FIRST_BEHAVIOUR", "down")
    monkeypatch.setenv("SECOND_BEHAVIOUR", "down")
    with pytest.raises(MessagingError) as exc:
        messaging.send(email())
    assert not exc.value.permanent and "first down" in str(exc.value) and "second down" in str(exc.value)


def test_a_channel_with_no_providers_is_off():
    assert not messaging.is_enabled("email")
    with pytest.raises(ConfigError):
        messaging.send(email())


def test_settings_can_come_from_a_mapping_instead_of_the_environment(flaky):
    result = messaging.send(email(), providers=["first"], settings={"first": {"BEHAVIOUR": "ok"}})
    assert result.provider == "first"
    assert ProviderConfig("X", {"api_key": "k"}).get("API_KEY") == "k"


def test_the_build_has_many_providers_per_channel():
    available = messaging.available()
    assert {"smtp", "ses", "resend", "sendgrid", "mailgun", "postmark", "brevo"} <= set(available["email"])
    assert {"twilio", "vonage", "unifonic"} <= set(available["sms"])
    assert {"twilio", "meta"} <= set(available["whatsapp"])
    assert {"webhook", "bot"} <= set(available["slack"])


class FakeResponse:
    def __init__(self, status, body=None, headers=None):
        self.status_code, self._body, self.headers = status, body or {}, headers or {}
        self.ok = status < 400
        self.text = str(body)
        self.content = b"x"

    def json(self):
        return self._body


@pytest.mark.parametrize("status, permanent", [(400, True), (401, True), (422, True), (429, False), (503, False)])
def test_http_failures_are_classified(monkeypatch, status, permanent):
    monkeypatch.setenv("RESEND_API_KEY", "k")
    monkeypatch.setenv("EMAIL_FROM", "CX <no-reply@cx.example>")
    monkeypatch.setattr(requests, "post", lambda *a, **kw: FakeResponse(status, {"message": "no"}))
    with pytest.raises(MessagingError) as exc:
        messaging.send(email(), providers=["resend"])
    assert exc.value.permanent is permanent


def test_resend_gets_the_sender_and_an_idempotency_key(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "k")
    monkeypatch.setenv("EMAIL_FROM", "CX <no-reply@cx.example>")
    seen = {}

    def post(url, **kw):
        seen.update(url=url, **kw)
        return FakeResponse(200, {"id": "re_1"})

    monkeypatch.setattr(requests, "post", post)
    message = Message(channel="email", to="a@b.co", subject="S", text="T", html="<p>T</p>", reference="delivery-9")
    assert messaging.send(message, providers=["resend"]).message_id == "re_1"
    assert seen["url"] == "https://api.resend.com/emails"
    assert seen["json"]["from"] == "CX <no-reply@cx.example>" and seen["json"]["html"] == "<p>T</p>"
    assert seen["headers"]["Idempotency-Key"] == "delivery-9"


def test_a_network_error_is_worth_retrying(monkeypatch):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.com/services/x")

    def boom(*a, **kw):
        raise requests.ConnectionError("no route")

    monkeypatch.setattr(requests, "post", boom)
    with pytest.raises(MessagingError) as exc:
        messaging.send(Message(channel="slack", to="", text="hi"), providers=["webhook"])
    assert not exc.value.permanent


# ── the bell ──────────────────────────────────────────────────────────────────

def note(id, read=False):
    return Notification(id=id, organisation_id=10, recipient_id=2, template="task.assigned",
                        params={"task": f"T{id}"}, link=None, created_at=datetime(2026, 11, 1, tzinfo=timezone.utc),
                        read_at=datetime(2026, 11, 2, tzinfo=timezone.utc) if read else None)


def test_the_list_is_the_callers_own_rendered_in_their_language(client, monkeypatch):
    seen = {}

    def list_for(db, **kw):
        seen.update(kw)
        return [note(9), note(8), note(7)]

    monkeypatch.setattr(repo, "list_for", list_for)
    monkeypatch.setattr(repo, "unread_count", lambda db, recipient_id: 4)
    res = client.get("/notifications?limit=2", headers={**employee_token(id=2), "Accept-Language": "ar-EG,ar;q=0.9"})
    assert res.status_code == 200
    body = res.json()
    assert seen["recipient_id"] == 2 and seen["limit"] == 3
    assert [i["id"] for i in body["items"]] == [9, 8] and body["next_before_id"] == 8 and body["unread"] == 4
    assert body["items"][0]["title"] == "مهمة جديدة: T9"


def test_marking_read_only_touches_the_callers_notifications(client, db, monkeypatch):
    seen = {}
    monkeypatch.setattr(repo, "mark_read", lambda db, **kw: seen.update(kw) or 1)
    monkeypatch.setattr(repo, "unread_count", lambda db, recipient_id: 0)
    res = client.post("/notifications/5/read", headers=employee_token(id=2))
    assert res.json() == {"marked": 1, "unread": 0}
    assert seen["recipient_id"] == 2 and seen["ids"] == [5] and db.commits == 1
    client.post("/notifications/read-all", headers=employee_token(id=2))
    assert seen["ids"] is None


def test_marking_someone_elses_notification_unread_is_not_found(client, monkeypatch):
    monkeypatch.setattr(repo, "mark_unread", lambda db, **kw: 0)
    assert client.post("/notifications/5/unread", headers=employee_token(id=2)).status_code == 404


def test_channels_and_tests_are_for_organisation_admins(client):
    assert client.get("/notifications/channels", headers=employee_token()).status_code == 403
    assert client.post("/notifications/test", json={"channels": ["in_app"]}, headers=employee_token()).status_code == 403


def test_a_test_sends_at_once_and_says_how_it_went(client, db, people, monkeypatch):
    monkeypatch.setenv("EMAIL_PROVIDERS", "log")
    res = client.post("/notifications/test", json={"channels": ["in_app", "email", "sms"]},
                      headers=employee_token(id=2, is_admin=True))
    assert res.status_code == 200, res.text
    results = {r["channel"]: r for r in res.json()["results"]}
    assert results["in_app"]["status"] == "sent"
    assert results["email"]["status"] == "sent" and results["email"]["provider"] == "log"
    assert results["sms"]["status"] == "skipped"
    [sent] = added(db, NotificationDelivery)
    assert sent.status == "sent" and db.commits == 1


def test_the_channel_list_shows_what_is_switched_on(client, monkeypatch):
    monkeypatch.setenv("EMAIL_PROVIDERS", "resend,smtp")
    res = client.get("/notifications/channels", headers=employee_token(is_admin=True))
    channels = {c["channel"]: c for c in res.json()["channels"]}
    assert channels["email"]["enabled"] and channels["email"]["providers"] == ["resend", "smtp"]
    assert not channels["sms"]["enabled"] and "unifonic" in channels["sms"]["available"]
