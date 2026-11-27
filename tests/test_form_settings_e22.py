"""E2.2 form settings: dates, endings, notifications, one response per
person, save and resume, CAPTCHA, prefilled links, anonymous mode, shuffling,
the progress bar and editing a submitted response. Every public link and
every new route stays inside the form's organisation."""

from datetime import datetime, timedelta, timezone

import pytest

from common.services import captcha, signing
from config import FormsEnv
from modules.customers import repository as customers_repo
from modules.customers.model import Customer
from modules.employees import repository as employees_repo
from modules.forms import behaviour
from modules.forms import repository as forms_repo
from modules.forms.dto import FormSettings, stored_settings
from modules.forms.model import FormField
from modules.notifications import service as notifications
from modules.results import repository as results_repo
from modules.submissions import handlers
from modules.submissions import repository as subs_repo
from modules.submissions.model import Submission
from tests.conftest import employee_token, make_form, make_submission, republish

NOW = datetime.now(timezone.utc)
DETAILS = {"email": "ann@acme.io", "first_name": "Ann", "last_name": "Lee"}


def with_settings(form, **settings):
    form.settings = {**(form.settings or {}), **settings}
    return form


def questionnaire(**settings):
    """A published questionnaire in org 10 (public token "tok"), sections 1
    and 2, question 101 (single choice A/B, required, worth 1) and 102 (text)."""
    form = make_form(type="questionnaire", max_attempts=None, time_limit_minutes=None)
    return with_settings(form, **settings)


@pytest.fixture
def stub_public(monkeypatch):
    holder = {"form": questionnaire(), "count": 0, "subs": {}}
    monkeypatch.setattr(forms_repo, "get_form_by_token", lambda db, t: holder["form"] if t == "tok" else None)
    monkeypatch.setattr(subs_repo, "count_finalized_attempts", lambda db, **kw: holder["count"])
    monkeypatch.setattr(subs_repo, "get_submission", lambda db, sid: holder["subs"].get(sid))
    monkeypatch.setattr(customers_repo, "get_by_email", lambda db, **kw: None)
    return holder


def public_submit(client, body, ip="203.0.113.9"):
    return client.post("/public/forms/tok/submit", json=body, headers={"X-Forwarded-For": ip})


def added(db, kind):
    return [o for o in db.added if isinstance(o, kind)]


# ── signing and settings ────────────────────────────────────────────────────

def test_signed_tokens_refuse_tampering_other_purposes_and_expiry():
    token = signing.sign({"f": 7}, purpose="prefill", secret="s")
    assert signing.verify(token, purpose="prefill", secret="s") == {"f": 7}
    assert signing.verify(token, purpose="attempt", secret="s") is None
    assert signing.verify(token, purpose="prefill", secret="other") is None
    body, sig = token.split(".")
    forged = signing.sign({"f": 8}, purpose="prefill", secret="s").split(".")[0] + "." + sig
    assert signing.verify(forged, purpose="prefill", secret="s") is None
    old = signing.sign({"f": 7}, purpose="prefill", secret="s", expires_at=1)
    assert signing.verify(old, purpose="prefill", secret="s") is None
    assert signing.verify("junk", purpose="prefill", secret="s") is None


def test_new_settings_are_stored_only_when_set():
    assert stored_settings(FormSettings()) == {
        "time_limit_minutes": None, "max_attempts": None, "results_revealed": False, "theme": None,
    }
    opens = datetime(2026, 12, 1, 9, tzinfo=timezone.utc)
    stored = stored_settings(FormSettings(opens_at=opens, captcha=False))
    assert stored["opens_at"] == "2026-12-01T09:00:00Z" and stored["captcha"] is False


@pytest.mark.parametrize("settings", [
    {"opens_at": "2026-12-02T00:00:00Z", "closes_at": "2026-12-01T00:00:00Z"},
    {"opens_at": "2026-12-02T00:00:00"},  # no time zone
    {"endings": [{"id": 1, "title": "Bye", "redirect_url": "javascript:alert(1)"}]},
    {"endings": [{"id": 1, "title": "A"}, {"id": 1, "title": "B"}]},
    {"endings": [{"id": 1, "title": "A", "min_score": 80, "max_score": 20}]},
    {"hidden_fields": [{"key": "Branch Name"}]},
    {"edit_window_minutes": 0},
    {"notify": {"employee_ids": [1], "channels": ["pigeon"]}},
])
def test_bad_settings_are_refused(client, settings, monkeypatch):
    monkeypatch.setattr(forms_repo, "create_form", lambda *a, **k: pytest.fail("must not be created"))
    res = client.post("/forms", headers=employee_token(id=1, permissions=["forms:create"]), json={
        "name": "S", "type": "questionnaire", "submitter_type": ["customer"],
        "settings": settings, "fields": [{"question": "Q", "type": "text"}],
    })
    assert res.status_code == 422, res.text


def test_notify_only_people_in_the_organisation(client, monkeypatch):
    form = make_form(is_active=False)
    monkeypatch.setattr(forms_repo, "get_form", lambda db, fid: form)
    seen = {}

    def ids_in_organisation(db, *, organisation_id, employee_ids):
        seen["org"] = organisation_id
        return {3}

    monkeypatch.setattr(employees_repo, "ids_in_organisation", ids_in_organisation)
    res = client.patch("/forms/7", headers=employee_token(id=1),
                       json={"settings": {"notify": {"employee_ids": [3, 99]}}})
    assert res.status_code == 422
    assert res.json()["error"] == "forms.notify_unknown_people" and "99" in res.json()["detail"]
    assert seen["org"] == 10  # the caller's organisation, from the token


# ── dates (T2.2.1) ──────────────────────────────────────────────────────────

def test_availability_follows_the_dates():
    form = questionnaire(opens_at=(NOW + timedelta(hours=1)).isoformat())
    assert behaviour.availability(form) == behaviour.NOT_YET_OPEN
    form = questionnaire(closes_at=(NOW - timedelta(minutes=1)).isoformat())
    assert behaviour.availability(form) == behaviour.CLOSED
    assert behaviour.availability(form, grace=timedelta(minutes=5)) == behaviour.OPEN


def test_a_closed_public_form_serves_no_questions(client, stub_public):
    stub_public["form"] = questionnaire(
        closes_at=(NOW - timedelta(days=1)).isoformat(), closed_message="See you next month",
    )
    body = client.get("/public/forms/tok").json()
    assert body["availability"] == "closed" and body["closed_message"] == "See you next month"
    assert body["fields"] == [] and body["sections"] is None
    res = public_submit(client, {"customer": DETAILS, "answers": {"101": "A"}})
    assert res.status_code == 409 and res.json()["error"] == "forms.closed_message"


def test_employees_cant_start_before_the_form_opens(client, monkeypatch):
    form = with_settings(make_form(), opens_at=(NOW + timedelta(days=1)).isoformat())
    monkeypatch.setattr(forms_repo, "get_form", lambda db, fid: form)
    res = client.post("/submissions/start", headers=employee_token(id=2), json={"form_id": 7})
    assert res.status_code == 409 and res.json()["error"] == "submissions.not_open_yet"


# ── endings (T2.2.2) ────────────────────────────────────────────────────────

ENDINGS = [
    {"id": 1, "title": "Great", "min_score": 50},
    {"id": 2, "title": "Took the other path", "section_id": 1},
    {"id": 3, "title": "Thanks", "redirect_url": "https://acme.example/thanks"},
]


def test_the_first_matching_ending_wins():
    form = questionnaire(endings=ENDINGS)
    assert behaviour.pick_ending(form, score=80, last_section_id=2).id == 1
    assert behaviour.pick_ending(form, score=10, last_section_id=1).id == 2
    assert behaviour.pick_ending(form, score=10, last_section_id=2).id == 3
    assert behaviour.pick_ending(questionnaire(), score=10, last_section_id=2) is None


def test_a_public_submission_returns_its_ending(client, stub_public):
    stub_public["form"] = questionnaire(endings=ENDINGS)
    # 101 right (1 of 2 points in section 1 alone weighs 1/4): score 25
    res = public_submit(client, {"customer": DETAILS, "answers": {"101": "A"}})
    assert res.status_code == 201, res.text
    assert res.json()["ending"] == {"id": 3, "title": "Thanks", "redirect_url": "https://acme.example/thanks"}


# ── notifications (T2.2.3) ──────────────────────────────────────────────────

def test_each_response_notifies_the_chosen_people(db, monkeypatch):
    form = with_settings(make_form(), notify={"employee_ids": [3, 4], "channels": ["in_app", "email"]})
    sub = make_submission(form, status="submitted", contact=DETAILS, user_id=None)
    monkeypatch.setattr(subs_repo, "get_submission", lambda db, sid: sub)
    calls = []
    monkeypatch.setattr(notifications, "notify", lambda db, **kw: calls.append(kw))
    event = type("E", (), {"payload": {"submission_id": 500}})()
    handlers.notify_on_response(db, event)
    (call,) = calls
    assert call["organisation_id"] == 10 and call["recipient_ids"] == [3, 4]
    assert call["template"] == "submission.received" and call["params"]["respondent"] == "Ann Lee"
    assert call["channels"] == ["in_app", "email"] and call["link"] == "/submissions/500"


def test_anonymous_responses_notify_without_a_name(db, monkeypatch):
    form = with_settings(make_form(type="questionnaire"), anonymous=True, notify={"employee_ids": [3]})
    sub = make_submission(form, status="submitted", user_id=None, respondent_key="k" * 64)
    monkeypatch.setattr(subs_repo, "get_submission", lambda db, sid: sub)
    calls = []
    monkeypatch.setattr(notifications, "notify", lambda db, **kw: calls.append(kw))
    handlers.notify_on_response(db, type("E", (), {"payload": {"submission_id": 500}})())
    assert calls[0]["template"] == "submission.received_anonymous" and "respondent" not in calls[0]["params"]


def test_no_recipients_no_notification(db, monkeypatch):
    sub = make_submission(make_form(), status="submitted")
    monkeypatch.setattr(subs_repo, "get_submission", lambda db, sid: sub)
    monkeypatch.setattr(notifications, "notify", lambda db, **kw: pytest.fail("nobody to tell"))
    handlers.notify_on_response(db, type("E", (), {"payload": {"submission_id": 500}})())


def test_the_handler_is_registered_for_finished_responses():
    from common.events.registry import handlers_for

    assert "submissions.notify_on_response" in handlers_for("submission.submitted")
    assert "submissions.notify_on_response" in handlers_for("submission.late")


# ── one response per person (T2.2.4) ────────────────────────────────────────

def test_one_response_per_person_for_employees(client, monkeypatch):
    form = with_settings(make_form(type="questionnaire", max_attempts=5), one_response_per_person=True)
    monkeypatch.setattr(forms_repo, "get_form", lambda db, fid: form)
    monkeypatch.setattr(subs_repo, "find_open_submission", lambda db, **kw: None)
    monkeypatch.setattr(subs_repo, "count_finalized_attempts", lambda db, **kw: 1)
    res = client.post("/submissions/start", headers=employee_token(id=2), json={"form_id": 7})
    assert res.status_code == 409 and res.json()["error"] == "submissions.already_responded"


def test_one_response_per_person_on_public_links(client, db, stub_public):
    stub_public["form"] = questionnaire(one_response_per_person=True)
    stub_public["count"] = 1
    res = public_submit(client, {"customer": DETAILS, "answers": {"101": "A"}})
    assert res.status_code == 409 and res.json()["error"] == "public_forms.already_responded"
    assert not added(db, Submission)


# ── anonymous mode (T2.2.8) ─────────────────────────────────────────────────

def test_anonymous_public_responses_store_no_identity(client, db, stub_public, monkeypatch):
    stub_public["form"] = questionnaire(anonymous=True, one_response_per_person=True)
    seen = {}

    def count(db, **kw):
        seen.update(kw)
        return 0

    monkeypatch.setattr(subs_repo, "count_finalized_attempts", count)
    res = public_submit(client, {"answers": {"101": "A"}, "device_id": "browser-1234"})
    assert res.status_code == 201, res.text
    assert not added(db, Customer)
    (sub,) = added(db, Submission)
    assert (sub.customer_id, sub.user_id, sub.contact) == (None, None, None)
    assert sub.respondent_key == behaviour.respondent_key(7, "device", "browser-1234")
    # the same browser is counted, by its keyed stand-in
    assert seen["respondent_key"] == sub.respondent_key and seen["customer_id"] is None


def test_anonymous_and_one_response_needs_the_browser_id(client, stub_public):
    stub_public["form"] = questionnaire(anonymous=True, one_response_per_person=True)
    res = public_submit(client, {"answers": {"101": "A"}})
    assert res.status_code == 422 and res.json()["error"] == "public_forms.device_required"


def test_named_public_forms_still_need_details(client, stub_public):
    res = public_submit(client, {"answers": {"101": "A"}})
    assert res.status_code == 422 and res.json()["error"] == "public_forms.details_required"


def test_anonymous_employee_attempts_carry_no_id_but_stay_theirs(client, monkeypatch):
    form = with_settings(make_form(type="questionnaire", max_attempts=None), anonymous=True)
    monkeypatch.setattr(forms_repo, "get_form", lambda db, fid: form)
    monkeypatch.setattr(subs_repo, "count_finalized_attempts", lambda db, **kw: 0)
    holder, lookups = {}, []

    def find_open(db, **kw):
        lookups.append(kw)
        return None

    def create(db, **kw):
        holder["kw"] = kw
        holder["sub"] = make_submission(form, user_id=kw["user_id"], respondent_key=kw["respondent_key"])
        return holder["sub"]

    monkeypatch.setattr(subs_repo, "find_open_submission", find_open)
    monkeypatch.setattr(subs_repo, "create_submission", create)
    monkeypatch.setattr(subs_repo, "get_submission", lambda db, sid: holder.get("sub"))
    res = client.post("/submissions/start", headers=employee_token(id=2), json={"form_id": 7})
    assert res.status_code == 201, res.text
    assert holder["kw"]["user_id"] is None and holder["kw"]["respondent_key"]
    assert lookups[0]["user_id"] is None and lookups[0]["respondent_key"] == holder["kw"]["respondent_key"]
    assert res.json()["user_id"] is None and res.json()["anonymous"] is True
    # the respondent can carry on; a colleague can't
    assert client.get("/submissions/500/form", headers=employee_token(id=2)).status_code == 200
    assert client.get("/submissions/500/form", headers=employee_token(id=3)).status_code == 403


def test_exams_are_never_anonymous():
    assert not behaviour.is_anonymous(with_settings(make_form(), anonymous=True))


# ── shuffling (T2.2.9) ──────────────────────────────────────────────────────

def shuffle_form():
    form = make_form(type="questionnaire", sections=None)
    form.fields = [
        FormField(id=1, key="h", question="Intro", type="heading", order=0, score_weight=0, is_required=False),
        *[
            FormField(id=10 + i, key=f"q{i}", question=f"Q{i}", type="single_choice",
                      options=["a", "b", "c", "d"], order=1 + i, score_weight=0, is_required=False,
                      config={"option_images": [{"file_id": 1}, None, {"file_id": 3}, None]})
            for i in range(6)
        ],
    ]
    republish(form)
    return with_settings(form, shuffle_questions=True, shuffle_options=True)


def test_shuffling_is_kept_per_seed_and_display_blocks_stay():
    form = shuffle_form()
    one, again, other = (behaviour.shuffled_order(form, s) for s in (11, 11, 12))
    assert one == again and one != other
    assert one["fields"][0] == 1  # the heading stays first
    assert sorted(one["fields"]) == [1, 10, 11, 12, 13, 14, 15]
    assert behaviour.shuffled_order(questionnaire(), 11) is None


def test_option_pictures_move_with_their_options():
    from modules.public_api.dto import PublicFormField

    form = shuffle_form()
    order = {"fields": [1, 10], "options": {"10": ["c", "a", "d", "b"]}}
    fields = [PublicFormField.model_validate(f) for f in form.fields[:2]]
    behaviour.apply_order(fields, order)
    q = fields[1]
    assert q.options == ["c", "a", "d", "b"]
    assert [img and img["file_id"] for img in q.config["option_images"]] == [3, 1, None, None]


def test_a_reload_with_the_attempt_token_keeps_the_order(client, db, stub_public, monkeypatch):
    from modules.forms import service as forms_service

    monkeypatch.setattr(forms_service, "media_for", lambda db, form, **kw: {})
    stub_public["form"] = form = shuffle_form()
    form.public_token = "tok"
    first = client.get("/public/forms/tok").json()
    again = client.get("/public/forms/tok", params={"attempt": first["attempt"]}).json()
    order = lambda body: [f["id"] for f in sorted(body["fields"], key=lambda f: f["order"])]  # noqa: E731
    assert first["attempt"] and order(first) == order(again)
    assert [f["options"] for f in first["fields"]] == [f["options"] for f in again["fields"]]
    # the order shown is kept with the response
    res = public_submit(client, {"customer": DETAILS, "answers": {}, "attempt": first["attempt"]})
    assert res.status_code == 201, res.text
    assert added(db, Submission)[0].question_order["fields"] == order(first)


def test_a_forged_attempt_token_is_ignored():
    assert behaviour.seed_from_attempt(7, "x.y") is None
    assert behaviour.seed_from_attempt(8, behaviour.attempt_token(7, 5)) is None
    assert behaviour.seed_from_attempt(7, behaviour.attempt_token(7, 5)) == 5


# ── progress bar (T2.2.10) and CAPTCHA (T2.2.6) ────────────────────────────

def test_the_public_form_serves_its_respondent_settings(client, stub_public, monkeypatch):
    stub_public["form"] = questionnaire(show_progress=True, allow_resume=True, edit_window_minutes=60)
    monkeypatch.setattr(FormsEnv, "CAPTCHA_PROVIDER", "turnstile")
    monkeypatch.setattr(FormsEnv, "CAPTCHA_SITE_KEY", "site")
    monkeypatch.setattr(FormsEnv, "CAPTCHA_SECRET_KEY", "secret")
    body = client.get("/public/forms/tok").json()
    assert (body["show_progress"], body["allow_resume"], body["edit_window_minutes"]) == (True, True, 60)
    assert body["captcha"] == {"provider": "turnstile", "site_key": "site"}
    assert "secret" not in str(body)


@pytest.fixture
def captcha_on(monkeypatch):
    monkeypatch.setattr(FormsEnv, "CAPTCHA_PROVIDER", "hcaptcha")
    monkeypatch.setattr(FormsEnv, "CAPTCHA_SITE_KEY", "site")
    monkeypatch.setattr(FormsEnv, "CAPTCHA_SECRET_KEY", "secret")
    calls = []

    def post(url, data, timeout):
        calls.append(data)
        ok = data["response"] == "good"
        return type("R", (), {"raise_for_status": lambda self: None, "json": lambda self: {"success": ok}})()

    monkeypatch.setattr(captcha.requests, "post", post)
    return calls


def test_a_failed_captcha_writes_nothing(client, db, stub_public, captcha_on):
    res = public_submit(client, {"customer": DETAILS, "answers": {"101": "A"}, "captcha_token": "bad"})
    assert res.status_code == 422 and res.json()["error"] == "public_forms.captcha_failed"
    assert db.added == [] and db.commits == 0
    assert captcha_on[0]["remoteip"] == "203.0.113.9" and captcha_on[0]["secret"] == "secret"
    res = public_submit(client, {"customer": DETAILS, "answers": {"101": "A"}, "captcha_token": "good"})
    assert res.status_code == 201, res.text


def test_a_form_can_turn_its_captcha_off(client, stub_public, captcha_on):
    stub_public["form"] = questionnaire(captcha=False)
    assert public_submit(client, {"customer": DETAILS, "answers": {"101": "A"}}).status_code == 201
    assert captcha_on == []


def test_an_unreachable_captcha_provider_is_a_503(client, db, stub_public, monkeypatch, captcha_on):
    def down(*a, **k):
        raise captcha.requests.ConnectionError("down")

    monkeypatch.setattr(captcha.requests, "post", down)
    res = public_submit(client, {"customer": DETAILS, "answers": {"101": "A"}, "captcha_token": "good"})
    assert res.status_code == 503 and db.added == []


# ── prefilled links (T2.2.7) ────────────────────────────────────────────────

def prefill_link(client, body, *, org=10, admin=True):
    return client.post("/forms/7/prefill-links", headers=employee_token(id=1, organisation_id=org, is_admin=admin),
                       json=body)


@pytest.fixture
def prefill_form(monkeypatch, stub_public):
    form = questionnaire(hidden_fields=[{"key": "branch"}, {"key": "employee_id"}])
    stub_public["form"] = form
    monkeypatch.setattr(forms_repo, "get_form", lambda db, fid: form if fid == 7 else None)
    return form


def test_prefilled_values_reach_the_response_and_cant_be_changed(client, db, prefill_form):
    res = prefill_link(client, {"hidden": {"branch": "Cairo"}, "answers": {"101": "B"}, "expires_in_days": 7})
    assert res.status_code == 201, res.text
    token = res.json()["token"]
    loaded = client.get("/public/forms/tok", params={"prefill": token}).json()
    assert loaded["prefill_answers"] == {"101": "B"}
    assert "Cairo" not in str(loaded)  # hidden values aren't echoed
    res = public_submit(client, {"customer": DETAILS, "answers": {"101": "A"}, "prefill": token})
    assert res.status_code == 201, res.text
    assert added(db, Submission)[0].hidden_fields == {"branch": "Cairo"}
    # one changed character and the link is refused
    tampered = token[:-2] + ("A" if token[-2] != "A" else "B") + token[-1]
    res = public_submit(client, {"customer": DETAILS, "answers": {"101": "A"}, "prefill": tampered})
    assert res.status_code == 422 and res.json()["error"] == "public_forms.prefill_invalid"


def test_a_prefilled_link_for_another_form_is_refused(client, prefill_form):
    other = behaviour.prefill_token(8, hidden={"branch": "X"}, answers={}, expires_at=None)
    res = client.get("/public/forms/tok", params={"prefill": other})
    assert res.status_code == 422


@pytest.mark.parametrize("body, code", [
    ({"hidden": {"salary": "1"}}, "forms.unknown_hidden_field"),
    ({"answers": {"999": "x"}}, "forms.prefill_unknown_question"),
    ({"answers": {"101": "Z"}}, "submissions.answer_invalid"),
])
def test_prefilled_links_only_carry_what_the_form_declares(client, prefill_form, body, code):
    res = prefill_link(client, body)
    assert res.status_code == 422 and res.json()["error"] == code


def test_another_organisation_cant_make_prefilled_links(client, prefill_form):
    assert prefill_link(client, {"hidden": {"branch": "Cairo"}}, org=99).status_code == 404


def test_making_a_prefilled_link_is_audited_without_its_values(client, db, prefill_form):
    prefill_link(client, {"hidden": {"branch": "Cairo"}})
    (entry,) = [o for o in db.added if type(o).__name__ == "AuditEvent"]
    assert entry.action == "form.prefill_link_created" and "Cairo" not in str(entry.data)


def test_employee_attempts_start_from_a_prefilled_link(client, monkeypatch, prefill_form):
    prefill_form.submitter_type = ["employee", "customer"]
    holder = {}
    monkeypatch.setattr(subs_repo, "find_open_submission", lambda db, **kw: None)

    def create(db, **kw):
        holder.update(kw)
        return make_submission(prefill_form, answers=kw["answers"])

    monkeypatch.setattr(subs_repo, "create_submission", create)
    token = prefill_link(client, {"hidden": {"employee_id": "12"}, "answers": {"101": "A"}}).json()["token"]
    res = client.post("/submissions/start", headers=employee_token(id=2), json={"form_id": 7, "prefill": token})
    assert res.status_code == 201, res.text
    assert holder["hidden_fields"] == {"employee_id": "12"} and holder["answers"] == {"101": "A"}


# ── save and continue later (T2.2.5) ────────────────────────────────────────

def test_resume_is_off_unless_the_form_allows_it(client, stub_public):
    res = client.post("/public/forms/tok/drafts", json={"answers": {"101": "A"}})
    assert res.status_code == 409 and res.json()["error"] == "public_forms.resume_off"


def test_a_saved_draft_resumes_and_finishes_as_the_same_response(client, db, stub_public):
    stub_public["form"] = form = questionnaire(allow_resume=True)
    res = client.post("/public/forms/tok/drafts", json={
        "answers": {"101": "B", "999": "dropped"}, "customer": {"email": "ann@", "first_name": "Ann"},
    })
    assert res.status_code == 201, res.text
    resume = res.json()["resume_token"]
    (draft,) = added(db, Submission)
    assert draft.status == "in_progress" and draft.answers == {"101": "B"}
    assert draft.expires_at > NOW + timedelta(days=FormsEnv.PUBLIC_DRAFT_TTL_DAYS - 1)
    draft.form, draft.form_version = form, form.current_version
    stub_public["subs"][draft.id] = draft

    body = client.get(f"/public/forms/tok/drafts/{resume}").json()
    assert body["answers"] == {"101": "B"} and body["customer"] == {"email": "ann@", "first_name": "Ann",
                                                                    "last_name": None, "phone": None}
    assert body["form"]["fields"][0]["id"] == 101

    res = public_submit(client, {"customer": DETAILS, "answers": {"101": "A"}, "resume_token": resume})
    assert res.status_code == 201, res.text
    assert res.json()["submission_id"] == draft.id and len(added(db, Submission)) == 1
    assert draft.status == "submitted" and draft.expires_at is None and draft.contact["email"] == "ann@acme.io"
    # a finished draft can't be resumed again
    again = client.get(f"/public/forms/tok/drafts/{resume}")
    assert again.status_code == 409 and again.json()["error"] == "public_forms.draft_finished"


def test_resume_links_only_open_their_own_draft(client, stub_public):
    stub_public["form"] = form = questionnaire(allow_resume=True)
    draft = make_submission(form, id=600, user_id=None, started_at=NOW)
    stub_public["subs"][600] = draft
    good = behaviour.resume_token(draft)
    assert client.get(f"/public/forms/tok/drafts/{good}").status_code == 200
    assert client.get(f"/public/forms/tok/drafts/600.{'A' * 43}").status_code == 404  # forged
    draft.form_id = 8  # the same row under another form's link
    assert client.get(f"/public/forms/tok/drafts/{good}").status_code == 404
    draft.form_id, draft.user_id = 7, 2  # an employee's attempt
    assert client.get(f"/public/forms/tok/drafts/{good}").status_code == 404


# ── editing a submitted response (T2.2.11) ──────────────────────────────────

@pytest.fixture
def no_value_rows(monkeypatch):
    monkeypatch.setattr(results_repo, "delete_values", lambda db, sid: None)
    monkeypatch.setattr(results_repo, "unit_of_values", lambda db, sid: 40)


def test_a_public_response_comes_with_an_edit_link_and_can_be_changed(client, db, stub_public, no_value_rows):
    stub_public["form"] = form = questionnaire(edit_window_minutes=30)
    res = public_submit(client, {"customer": DETAILS, "answers": {"101": "B"}})
    assert res.status_code == 201, res.text
    body = res.json()
    (sub,) = added(db, Submission)
    sub.form, sub.form_version = form, form.current_version
    stub_public["subs"][sub.id] = sub
    assert body["edit_token"] and datetime.fromisoformat(body["editable_until"]) > NOW

    got = client.get(f"/public/forms/tok/responses/{body['edit_token']}").json()
    assert got["answers"] == {"101": "B"}
    res = client.put(f"/public/forms/tok/responses/{body['edit_token']}", json={"answers": {"101": "A"}})
    assert res.status_code == 200, res.text
    assert sub.answers == {"101": "A"} and sub.edited_at is not None and sub.score > 0
    events = [o.event_type for o in db.added if type(o).__name__ == "OutboxEvent"]
    assert events[-1] == "submission.edited"
    audit = [o for o in db.added if type(o).__name__ == "AuditEvent"]
    assert audit[-1].action == "submission.edited"


def test_no_edit_link_without_an_edit_window(client, stub_public):
    res = public_submit(client, {"customer": DETAILS, "answers": {"101": "A"}})
    assert "edit_token" not in res.json()


def test_edits_stop_when_the_window_closes(client, monkeypatch, no_value_rows):
    form = with_settings(make_form(type="questionnaire"), edit_window_minutes=10)
    sub = make_submission(form, status="submitted", submitted_at=NOW - timedelta(minutes=11), answers={"101": "A"})
    monkeypatch.setattr(subs_repo, "get_submission", lambda db, sid: sub)
    monkeypatch.setattr(subs_repo, "save", lambda db, s: s)
    res = client.post("/submissions/500/edit", headers=employee_token(id=2), json={"answers": {"101": "B"}})
    assert res.status_code == 409 and res.json()["error"] == "submissions.edit_window_over"
    sub.submitted_at = NOW - timedelta(minutes=1)
    res = client.post("/submissions/500/edit", headers=employee_token(id=2), json={"answers": {"101": "B"}})
    assert res.status_code == 200, res.text
    assert sub.answers == {"101": "B"} and res.json()["editable_until"]


def test_exams_cant_be_edited_and_others_cant_edit(client, monkeypatch, no_value_rows):
    exam = with_settings(make_form(), edit_window_minutes=10)
    sub = make_submission(exam, status="submitted", submitted_at=NOW)
    monkeypatch.setattr(subs_repo, "get_submission", lambda db, sid: sub)
    res = client.post("/submissions/500/edit", headers=employee_token(id=2), json={"answers": {"101": "B"}})
    assert res.status_code == 409 and res.json()["error"] == "submissions.not_editable"
    sub.form = with_settings(make_form(type="questionnaire"), edit_window_minutes=10)
    assert client.post("/submissions/500/edit", headers=employee_token(id=3),
                       json={"answers": {"101": "B"}}).status_code == 403
    # another organisation's submission doesn't exist for them
    assert client.post("/submissions/500/edit", headers=employee_token(id=2, organisation_id=99),
                       json={"answers": {"101": "B"}}).status_code == 404


def test_edit_links_only_open_their_own_response(client, stub_public, no_value_rows):
    stub_public["form"] = form = questionnaire(edit_window_minutes=30)
    sub = make_submission(form, id=601, status="submitted", user_id=None, submitted_at=NOW)
    stub_public["subs"][601] = sub
    good = behaviour.edit_token(sub)
    assert client.get(f"/public/forms/tok/responses/{good}").status_code == 200
    # a resume token for the same row isn't an edit token
    assert client.get(f"/public/forms/tok/responses/{behaviour.resume_token(sub)}").status_code == 404
    sub.form_id = 8
    assert client.get(f"/public/forms/tok/responses/{good}").status_code == 404
