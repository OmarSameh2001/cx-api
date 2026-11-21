"""E1.4: per-form `settings` (T1.4.2) and per-question `config` (T1.4.1)."""

from datetime import datetime, timezone
from typing import get_args

import pytest

from modules.files import service as files
from modules.files.purposes import MB
from modules.forms import repository as forms_repo
from modules.forms.dto import QUESTION_CONFIG_SCHEMAS, FieldType
from modules.forms.model import Form, FormField
from tests.conftest import employee_token, make_form, republish


@pytest.fixture
def created(monkeypatch):
    """Captures what create_form would insert."""
    rows = []

    def create_form(db, *, data, fields, created_by, before_commit=None):
        form = Form(**data, created_by=created_by)
        form.id = 70 + len(rows)
        form.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        form.is_archived = False
        if form.is_active is None:
            form.is_active = True  # the column default
        form.fields = [FormField(id=900 + i, **{k: v for k, v in f.items() if k != "id"}) for i, f in enumerate(fields)]
        rows.append(form)
        return form

    monkeypatch.setattr(forms_repo, "create_form", create_form)
    monkeypatch.setattr(forms_repo, "form_has_submissions", lambda db, fid: False)
    return rows


def questionnaire(**extra):
    return {
        "name": "Branch survey",
        "type": "questionnaire",
        "submitter_type": ["customer"],
        "fields": [{"question": "How was it?", "type": "text"}],
        **extra,
    }


def post(client, body):
    return client.post("/forms", headers=employee_token(id=1, permissions=["forms:create"]), json=body)


# ── form settings ────────────────────────────────────────────────────────────

def test_settings_are_stored_and_served(client, created):
    res = post(client, questionnaire(settings={"max_attempts": 3, "results_revealed": True}))
    assert res.status_code == 201, res.text
    assert created[0].settings == {"time_limit_minutes": None, "max_attempts": 3, "results_revealed": True}
    body = res.json()
    assert body["settings"] == {"time_limit_minutes": None, "max_attempts": 3, "results_revealed": True}
    # the old top-level copies are still served
    assert (body["max_attempts"], body["results_revealed"]) == (3, True)


def test_top_level_settings_are_still_accepted(client, created):
    res = post(client, questionnaire(max_attempts=2, results_revealed=True))
    assert res.status_code == 201, res.text
    assert created[0].settings["max_attempts"] == 2
    assert created[0].settings["results_revealed"] is True


def test_settings_win_over_top_level_copies(client, created):
    res = post(client, questionnaire(max_attempts=2, settings={"max_attempts": 5}))
    assert res.status_code == 201, res.text
    assert created[0].settings["max_attempts"] == 5


def test_exam_defaults_to_one_attempt(client, created):
    res = post(client, {
        "name": "Quiz", "type": "exam", "submitter_type": ["employee"],
        "settings": {"time_limit_minutes": 20},
        "fields": [{"question": "Q", "type": "boolean", "right_answer": "true"}],
    })
    assert res.status_code == 201, res.text
    assert created[0].settings == {"time_limit_minutes": 20, "max_attempts": 1, "results_revealed": False}


@pytest.mark.parametrize("settings", [{"shuffle": True}, {"max_attempts": 0}, {"time_limit_minutes": "x"}])
def test_bad_settings_are_rejected(client, created, settings):
    assert post(client, questionnaire(settings=settings)).status_code == 422
    assert not created


@pytest.fixture
def editable(monkeypatch):
    form = make_form(is_active=False)
    monkeypatch.setattr(forms_repo, "get_form", lambda db, fid: form if fid == form.id else None)
    monkeypatch.setattr(forms_repo, "form_has_submissions", lambda db, fid: False)
    return form


def patch(client, body):
    return client.patch("/forms/7", headers=employee_token(id=1), json=body)


def test_update_merges_settings(client, editable):
    res = patch(client, {"settings": {"max_attempts": 4}})
    assert res.status_code == 200, res.text
    assert editable.settings == {"time_limit_minutes": 30, "max_attempts": 4, "results_revealed": False}
    assert res.json()["settings"]["time_limit_minutes"] == 30


def test_update_accepts_top_level_settings(client, editable):
    # what the current builder sends
    res = patch(client, {"time_limit_minutes": None, "max_attempts": None, "results_revealed": True})
    assert res.status_code == 200, res.text
    assert editable.settings == {"time_limit_minutes": None, "max_attempts": None, "results_revealed": True}


def test_update_null_results_revealed_leaves_it(client, editable):
    editable.results_revealed = True
    assert patch(client, {"results_revealed": None}).status_code == 200
    assert editable.settings["results_revealed"] is True


@pytest.mark.parametrize("body", [{"settings": None}, {"settings": {"results_revealed": None}}, {"settings": {"nope": 1}}])
def test_update_rejects_bad_settings(client, editable, body):
    assert patch(client, body).status_code == 422


def test_model_properties_read_and_write_settings():
    form = Form(settings={})
    assert (form.time_limit_minutes, form.max_attempts, form.results_revealed) == (None, None, False)
    before = form.settings
    form.results_revealed = True
    # a new dict, so SQLAlchemy sees the change
    assert form.settings is not before and form.settings == {"results_revealed": True}


def test_duplicate_keeps_settings_but_not_revealed_results(client, created, monkeypatch):
    form = make_form(settings={"time_limit_minutes": 30, "max_attempts": 2, "results_revealed": True})
    form.fields[0].config = None
    monkeypatch.setattr(forms_repo, "get_form", lambda db, fid: form)
    res = client.post("/forms/7/duplicate", headers=employee_token(id=1, is_admin=True))
    assert res.status_code == 201, res.text
    assert created[0].settings == {"time_limit_minutes": 30, "max_attempts": 2, "results_revealed": False}
    assert form.results_revealed is True


# ── question config ──────────────────────────────────────────────────────────

def test_every_question_type_has_a_config_schema():
    assert set(QUESTION_CONFIG_SCHEMAS) == set(get_args(FieldType))


def file_question(**extra):
    return {"question": "Your receipt", "type": "file", **extra}


def test_file_config_is_validated_and_stored(client, created):
    res = post(client, questionnaire(fields=[file_question(
        config={"max_mb": 2, "allowed_types": ["application/pdf"], "image": {"quality": 70, "format": None}},
    )]))
    assert res.status_code == 201, res.text
    stored = {"max_mb": 2.0, "allowed_types": ["application/pdf"], "image": {"quality": 70}}
    assert created[0].fields[0].config == stored
    assert res.json()["fields"][0]["config"] == stored


def test_empty_config_is_stored_as_none(client, created):
    assert post(client, questionnaire(fields=[file_question(config={})])).status_code == 201
    assert created[0].fields[0].config is None


@pytest.mark.parametrize("field", [
    {"question": "Q", "type": "text", "config": {"max_length": 10}},  # text has no config yet
    file_question(config={"max_mb": -1}),
    file_question(config={"max_size": 2}),  # typo
])
def test_bad_config_is_rejected(client, created, field):
    res = post(client, questionnaire(fields=[field]))
    assert res.status_code == 422
    assert not created


@pytest.fixture
def with_file_question(editable):
    editable.fields.append(FormField(
        id=103, question="Upload", type="file", options=["max_mb=5"], order=2,
        is_required=False, score_weight=0.0, section_id=2, config={"max_mb": 1.0},
    ))
    republish(editable)
    return editable


def resend(form, changes=None):
    """Every field as the builder sends it back, without `config`."""
    out = []
    for f in form.fields:
        out.append({
            "id": f.id, "question": f.question, "type": f.type, "options": f.options,
            "right_answer": f.right_answer, "order": f.order, "help_text": f.help_text,
            "is_required": f.is_required, "score_weight": f.score_weight,
            "section_id": f.section_id, "branching": f.branching, **(changes or {}).get(f.id, {}),
        })
    return out


def test_field_sent_without_config_keeps_it(client, with_file_question):
    res = patch(client, {"fields": resend(with_file_question), "sections": with_file_question.sections})
    assert res.status_code == 200, res.text
    assert with_file_question.fields[-1].config == {"max_mb": 1.0}


def test_field_config_can_be_changed_or_cleared(client, with_file_question):
    fields = resend(with_file_question, {103: {"config": {"max_mb": 3}}})
    assert patch(client, {"fields": fields, "sections": with_file_question.sections}).status_code == 200
    assert with_file_question.fields[-1].config == {"max_mb": 3.0}
    fields = resend(with_file_question, {103: {"config": None}})
    assert patch(client, {"fields": fields, "sections": with_file_question.sections}).status_code == 200
    assert with_file_question.fields[-1].config is None


def test_config_change_with_responses_waits_for_publish(client, with_file_question, monkeypatch):
    monkeypatch.setattr(forms_repo, "form_has_submissions", lambda db, fid: True)
    sections = with_file_question.sections
    unchanged = patch(client, {"fields": resend(with_file_question), "sections": sections})
    assert unchanged.status_code == 200, unchanged.text
    assert unchanged.json()["has_unpublished_changes"] is False
    changed = patch(client, {"fields": resend(with_file_question, {103: {"config": {"max_mb": 3}}}), "sections": sections})
    assert changed.status_code == 200
    assert changed.json()["has_unpublished_changes"] is True
    published = {f["id"]: f for f in with_file_question.current_version.snapshot["fields"]}
    assert published[103]["config"] == {"max_mb": 1.0}


def test_config_limits_go_on_top_of_option_limits():
    q = files.question_limits(
        ["max_mb=5", "types=image/*", "image.quality=85"],
        {"max_mb": 2, "image": {"max_side": 800}},
    )
    assert q["max_bytes"] == 2 * MB
    assert q["allowed_types"] == ("image/*",)  # from options, config didn't set types
    assert q["image"] == {"quality": 85, "max_side": 800}


def test_effective_limits_apply_question_config(monkeypatch):
    from modules.files import repository as files_repo

    monkeypatch.setattr(files_repo, "limits_for", lambda db, **kw: (None, None))
    lim = files.effective_limits(
        None, organisation_id=1, purpose="form_answer",
        question_config={"max_mb": 1, "allowed_types": ["application/pdf"]},
    )
    assert lim.max_bytes == 1 * MB
    assert lim.allowed_types == ("application/pdf",)


def test_respondents_get_the_question_config(client, monkeypatch, with_file_question):
    from modules.submissions import repository as subs_repo
    from tests.conftest import make_submission

    with_file_question.is_active = True
    sub = make_submission(with_file_question)
    monkeypatch.setattr(subs_repo, "get_submission", lambda db, sid: sub)
    monkeypatch.setattr(subs_repo, "save", lambda db, s: s)
    res = client.get("/submissions/500/form", headers=employee_token(id=2))
    assert res.status_code == 200, res.text
    assert res.json()["fields"][-1]["config"] == {"max_mb": 1.0}


def test_respondents_never_get_undeclared_config_keys(client, monkeypatch, with_file_question):
    from modules.submissions import repository as subs_repo
    from tests.conftest import make_submission

    # written around the schema, e.g. by hand in the database
    with_file_question.fields[-1].config = {"max_mb": 1.0, "reviewer_note": "secret"}
    with_file_question.fields[0].config = {"anything": "secret"}
    republish(with_file_question)
    sub = make_submission(with_file_question)
    monkeypatch.setattr(subs_repo, "get_submission", lambda db, sid: sub)
    monkeypatch.setattr(subs_repo, "save", lambda db, s: s)
    res = client.get("/submissions/500/form", headers=employee_token(id=2))
    assert res.status_code == 200, res.text
    assert "secret" not in res.text
    assert res.json()["fields"][-1]["config"] == {"max_mb": 1.0}


def test_public_link_hides_score_weights_and_undeclared_config(client, monkeypatch):
    form = make_form(type="questionnaire", is_active=True, submitter_type=["customer"])
    form.fields.append(FormField(
        id=103, question="Upload", type="file", order=2, is_required=False,
        score_weight=0.0, section_id=2, config={"max_mb": 1.0, "reviewer_note": "secret"},
    ))
    republish(form)
    monkeypatch.setattr(forms_repo, "get_form_by_token", lambda db, t: form if t == "tok" else None)
    res = client.get("/public/forms/tok")
    assert res.status_code == 200, res.text
    body = res.json()
    assert set(body["sections"][0]) == {"id", "title", "description", "order", "next_section_id"}
    for leaked in ("score_weight", "right_answer", "secret", "settings", "public_token", "Because of physics"):
        assert leaked not in res.text
    assert body["fields"][-1]["config"] == {"max_mb": 1.0}
