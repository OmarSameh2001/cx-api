"""E2.1: question types (config, answers, grading hook, result rows and
summaries), display blocks, pictures on forms and the form theme."""

from datetime import datetime, timezone
from types import SimpleNamespace
from typing import get_args

import pytest
from pydantic import ValidationError

from common.errors import AppError
from modules.ai.chatbot.form.schema import GeneratedFieldType
from modules.files import repository as files_repo
from modules.files import service as files
from modules.files.model import StoredFile
from modules.forms import repository as forms_repo
from modules.forms import service as forms_service
from modules.forms.dto import (
    DISPLAY_TYPES, GRID_TYPES, FieldType, FormFieldCreate, FormFieldRead, FormSettings,
    config_with_defaults, respondent_config, validate_question_config,
)
from modules.forms.model import Form, FormField
from modules.results import repository as results_repo
from modules.results import service as results_service
from modules.submissions import repository as subs_repo
from modules.submissions import service as subs_service
from modules.submissions.answer_rules import is_incomplete, validate_answer_values
from tests.conftest import employee_token, make_submission, republish

START = datetime(2026, 3, 1, 9, 0, tzinfo=timezone.utc)
GRID = {"rows": ["Speed", "Staff"], "columns": ["Bad", "OK", "Good"]}


def field(type_, *, id=1, options=None, config=None, **extra) -> FormField:
    return FormField(
        id=id, key=f"k{id}", question=f"Q{id}", type=type_, options=options, config=config,
        order=id, is_required=extra.pop("is_required", False), score_weight=extra.pop("score_weight", 0.0),
        section_id=None, **extra,
    )


def form_with(*fields, **overrides) -> Form:
    data = dict(
        id=40, name="Branch survey", type="questionnaire", is_active=True, is_archived=False,
        submitter_type=["customer", "employee"], organisation_id=10, created_by=1,
        created_at=START, public_token="tok", sections=None, settings={},
    )
    data.update(overrides)
    form = Form(**data)
    form.fields = list(fields)
    return form


def create(**extra) -> FormFieldCreate:
    return FormFieldCreate.model_validate({"question": "Q", **extra})


# ── config ───────────────────────────────────────────────────────────────────

def test_ai_generation_offers_only_types_that_need_no_setup():
    offered = set(get_args(GeneratedFieldType))
    assert offered <= set(get_args(FieldType))
    assert not offered & (GRID_TYPES | DISPLAY_TYPES | {"slider", "currency", "image_choice"})


@pytest.mark.parametrize("type_, config", [
    ("scale", {"min": 0, "max": 10, "allow_na": True}),
    ("rating", {"levels": 10}),
    ("nps", {"low_label": "Unlikely", "high_label": "Very likely"}),
    ("number", {"min": 0, "max": 99, "integer_only": True, "unit": "km"}),
    ("currency", {"currency": "EGP", "max": 500}),
    ("slider", {"min": 1, "max": 10, "step": 0.5}),
    ("long_text", {"max_length": 2000}),
    ("choice_grid", GRID),
    ("checkbox_grid", GRID),
    ("likert", {"rows": ["Clean"], "columns": ["No", "Yes"]}),
    ("video", {"url": "https://www.youtube.com/watch?v=dQw4w9WgXcQ"}),
    ("video", {"url": "https://vimeo.com/76979871"}),
    ("image", {"image": {"file_id": 5, "alt": "Our branch"}}),
])
def test_good_configs_are_stored(type_, config):
    assert validate_question_config(type_, config) == config


@pytest.mark.parametrize("type_, config", [
    ("scale", {"max": 2}),
    ("scale", {"max": 11}),
    ("scale", {"min": 2}),
    ("rating", {"levels": 12}),
    ("number", {"min": 5, "max": 1}),
    ("currency", {"currency": "EUR"}),
    ("currency", {"min": -1}),
    ("slider", {"min": 5, "max": 5}),
    ("slider", {"min": 0, "max": 10, "step": 3}),  # 10 isn't a whole number of 3s
    ("slider", {"min": 0, "max": 100000, "step": 1}),
    ("long_text", {"max_length": 50000}),
    ("choice_grid", {"rows": ["A"]}),  # no columns
    ("choice_grid", {"rows": ["A", "A"], "columns": ["x", "y"]}),
    ("checkbox_grid", {"rows": [], "columns": ["x", "y"]}),
    ("likert", {"rows": ["A"], "columns": ["only one"]}),
    ("video", {"url": "https://evil.example/watch?v=dQw4w9WgXcQ"}),
    ("video", {"url": "javascript:alert(1)"}),
    ("image", {}),  # an image block needs its picture
    ("text", {"image": {"file_id": 0}}),
    ("dropdown", {"option_images": []}),  # images on options are for choices with pictures
])
def test_bad_configs_are_rejected(type_, config):
    with pytest.raises(ValueError):
        validate_question_config(type_, config)


def test_grids_need_rows_even_when_no_config_is_sent():
    with pytest.raises(ValidationError):
        create(type="choice_grid")


def test_defaults_are_not_stored_but_are_served():
    assert validate_question_config("scale", {"min": 1, "max": 5, "allow_na": False}) is None
    assert config_with_defaults("scale", None) == {"min": 1, "max": 5, "allow_na": False}
    assert respondent_config("rating", None) == {"levels": 5}
    assert respondent_config("likert", {"rows": ["Clean"]})["columns"][0] == "Strongly disagree"
    read = FormFieldRead.model_validate(field("scale", options=["Low", "High"]))
    assert read.config == {"min": 1, "max": 5, "allow_na": False}


def test_option_images_keep_their_positions():
    stored = validate_question_config("single_choice", {"option_images": [None, {"file_id": 3}]})
    assert stored == {"option_images": [None, {"file_id": 3}]}


def test_option_images_cannot_outnumber_options():
    with pytest.raises(ValidationError):
        create(type="single_choice", options=["A", "B"],
               config={"option_images": [{"file_id": 1}, {"file_id": 2}, {"file_id": 3}]})


def test_image_choice_needs_options():
    with pytest.raises(ValidationError):
        create(type="image_choice", options=["Only one"])
    assert create(type="image_choice", options=["Red", "Blue"], config={"multiple": True}).config == {"multiple": True}


def test_display_blocks_carry_nothing_to_answer():
    block = create(type="heading", question="Part two", options=["x", "y"], is_required=True,
                   score_weight=3, right_answer="x")
    assert (block.options, block.is_required, block.score_weight, block.right_answer) == (None, False, 0.0, None)
    # pictures and videos may go without a title; questions may not
    assert create(type="image", question="", config={"image": {"file_id": 4}}).question == ""
    with pytest.raises(ValidationError):
        create(type="text", question="")


def test_grids_keep_rows_and_columns_in_config_not_options():
    grid = create(type="likert", options=["stray"], config={"rows": ["Clean"]})
    assert grid.options is None


def test_dropdown_is_graded_and_can_branch():
    dropdown = create(type="dropdown", options=["A", "B"], right_answer="B", branching={"A": "end"})
    assert dropdown.right_answer == "B"
    with pytest.raises(ValidationError):
        create(type="dropdown", options=["A", "B"], right_answer="C")
    with pytest.raises(ValidationError):
        create(type="nps", branching={"9": "end"})
    f = field("dropdown", options=["A", "B"], right_answer="B", score_weight=1.0)
    assert subs_service._correctness_fraction(f, "B") == 1.0
    assert subs_service._correctness_fraction(f, "A") == 0.0


def test_theme_colours_must_be_hex():
    assert FormSettings.model_validate({"theme": {"primary_color": "#1A2b3C"}}).theme.primary_color == "#1A2b3C"
    for bad in ("red", "#12345", "#1234567", "url(x)"):
        with pytest.raises(ValidationError):
            FormSettings.model_validate({"theme": {"primary_color": bad}})


# ── answers ──────────────────────────────────────────────────────────────────

ANSWERS = [
    # type, config, options, good answers, bad answers
    ("scale", None, ["", ""], [1, 5, "3"], [0, 6, 2.5, True, "na"]),
    ("scale", {"min": 0, "max": 10, "allow_na": True}, None, [0, 10, "na"], [11, -1, "n/a"]),
    ("nps", None, None, [0, 10, "7"], [11, -1, 7.5]),
    ("rating", {"levels": 3}, None, [1, 3], [0, 4]),
    ("number", {"min": 0, "max": 10, "integer_only": True}, None, [0, 10, "4"], [-1, 11, 2.5, "abc", True]),
    ("number", None, None, [-3.75, 1e6], ["1e999", "nan"]),
    ("currency", {"max": 100}, None, [0, 99.99, "12.5"], [-1, 100.5, 1.234]),
    ("slider", {"min": 0, "max": 10, "step": 2.5}, None, [0, 2.5, 10], [1, 11, -2.5]),
    ("long_text", {"max_length": 10}, None, ["0123456789"], ["01234567890", 5]),
    ("dropdown", None, ["A", "B"], ["A"], ["C", ["A"]]),
    ("image_choice", None, ["Red", "Blue"], ["Red"], [["Red"], "Green"]),
    ("image_choice", {"multiple": True}, ["Red", "Blue"], [["Red", "Blue"]], [["Red", "Red"], ["Green"]]),
    ("time", None, None, ["09:30", "23:59"], ["24:00", "9:30", "09:60"]),
    ("choice_grid", GRID, None, [{"Speed": "OK"}, {"Speed": "Bad", "Staff": "Good"}],
     [{"Price": "OK"}, {"Speed": ["OK"]}, {"Speed": "Great"}, "OK"]),
    ("likert", {"rows": ["Clean"]}, None, [{"Clean": "Agree"}], [{"Clean": "Yes"}]),
    ("checkbox_grid", GRID, None, [{"Speed": ["OK", "Good"]}], [{"Speed": "OK"}, {"Speed": ["OK", "OK"]}]),
]


@pytest.mark.parametrize("type_, config, options, good, bad", ANSWERS)
def test_answers_are_checked_against_their_type(type_, config, options, good, bad):
    form = form_with(field(type_, options=options, config=config))
    for value in good:
        validate_answer_values(form, {"1": value})
    for value in bad:
        with pytest.raises(AppError):
            validate_answer_values(form, {"1": value})
            pytest.fail(f"{type_} accepted {value!r}")


def test_a_required_grid_needs_every_row():
    grid = field("choice_grid", config=GRID, is_required=True)
    assert is_incomplete(grid, {"Speed": "OK"})
    assert is_incomplete(grid, {"Speed": "OK", "Staff": ""})
    assert not is_incomplete(grid, {"Speed": "OK", "Staff": "Good"})
    assert is_incomplete(field("checkbox_grid", config=GRID), {"Speed": ["OK"], "Staff": []})


def test_display_blocks_take_no_answers():
    form = form_with(field("heading"), field("text", id=2))
    assert subs_service._prune_to_path(form, {"1": "sneaky", "2": "fine"}, None) == {"2": "fine"}
    with pytest.raises(AppError):
        validate_answer_values(form, {"1": "sneaky"})


# ── result rows ──────────────────────────────────────────────────────────────

@pytest.mark.parametrize("type_, value, column, stored", [
    ("nps", 9, "value_number", 9.0),
    ("rating", "4", "value_number", 4.0),
    ("number", "2.5", "value_number", 2.5),
    ("currency", 120.75, "value_number", 120.75),
    ("slider", 30, "value_number", 30.0),
    ("scale", "na", "value_text", "na"),
    ("dropdown", "A", "value_text", "A"),
    ("long_text", "Long story", "value_text", "Long story"),
    ("time", "09:30", "value_text", "09:30"),
    ("image_choice", "Red", "value_text", "Red"),
    ("image_choice", ["Red", "Blue"], "value_json", ["Red", "Blue"]),
    ("choice_grid", {"Speed": "OK"}, "value_json", {"Speed": "OK"}),
    ("checkbox_grid", {"Speed": ["OK"]}, "value_json", {"Speed": ["OK"]}),
])
def test_new_types_land_in_their_column(type_, value, column, stored):
    assert results_service._typed(type_, value) == {column: stored}


# ── summaries ────────────────────────────────────────────────────────────────

def test_nps_groups_and_score():
    assert results_service.nps_groups({"10": 3, "9": 1, "8": 2, "3": 2}) == {
        "promoters": 4, "passives": 2, "detractors": 2, "score": 25.0,
    }
    assert results_service.nps_groups({})["score"] is None
    assert [results_service.nps_group(p) for p in (10, 7, 6)] == ["promoter", "passive", "detractor"]


def test_a_scale_summary_lists_every_point_and_not_applicable():
    scale = field("scale", config={"min": 1, "max": 3, "allow_na": True})
    s = results_service.summarize_question(
        scale, {"submissions": 4, "avg_number": 2.5, "min_number": 2.0, "max_number": 3.0},
        {"2": 1, "3": 1, "na": 2}, {},
    )
    assert [(d.value, d.count) for d in s.distribution] == [("1", 0), ("2", 1), ("3", 1), ("na", 2)]
    assert (s.answered, s.avg, s.min, s.max) == (4, 2.5, 2.0, 3.0)


def test_a_choice_summary_keeps_answers_to_renamed_options():
    choice = field("dropdown", options=["Fast", "Slow"])
    s = results_service.summarize_question(choice, {"submissions": 3}, {"Fast": 2, "Quick": 1}, {})
    assert [(d.value, d.count) for d in s.distribution] == [("Fast", 2), ("Slow", 0), ("Quick", 1)]
    assert s.avg is None


def test_an_nps_summary_has_its_groups():
    s = results_service.summarize_question(field("nps"), {"submissions": 2}, {"10": 1, "0": 1}, {})
    assert len(s.distribution) == 11
    assert (s.nps.promoters, s.nps.detractors, s.nps.score) == (1, 1, 0.0)


def test_a_grid_summary_counts_rows_and_columns():
    s = results_service.summarize_question(
        field("choice_grid", config=GRID), {"submissions": 2}, {}, {"Speed": {"OK": 2}, "Staff": {"Good": 1}},
    )
    assert [(r.row, r.counts) for r in s.grid] == [
        ("Speed", {"Bad": 0, "OK": 2, "Good": 0}), ("Staff", {"Bad": 0, "OK": 0, "Good": 1}),
    ]


@pytest.fixture
def summary_form(monkeypatch):
    form = form_with(
        field("nps", id=1), field("choice_grid", id=2, config=GRID), field("long_text", id=3),
        field("heading", id=4),
    )
    republish(form)
    monkeypatch.setattr(forms_repo, "get_form", lambda db, fid: form if fid == form.id else None)
    calls = []

    def aggregate(db, **kw):
        calls.append(kw)
        if kw["group_by"] == ["question_key"]:
            return [{"question_key": "k1", "count": 2, "submissions": 2, "avg_number": 9.5,
                     "min_number": 9.0, "max_number": 10.0}], False
        return [{"question_key": "k1", "value": "10", "count": 1},
                {"question_key": "k1", "value": "9", "count": 1}], False

    def grid_counts(db, **kw):
        calls.append(kw)
        return [{"question_key": "k2", "row": "Speed", "column": "OK", "count": 2}]

    monkeypatch.setattr(results_repo, "aggregate", aggregate)
    monkeypatch.setattr(results_repo, "grid_counts", grid_counts)
    return form, calls


def test_the_summary_covers_every_question_of_the_published_version(client, summary_form):
    form, calls = summary_form
    res = client.post("/results/summary", headers=employee_token(id=1), json={"form_id": form.id})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["scope"] == "organisation"
    by_type = {q["type"]: q for q in body["questions"]}
    assert set(by_type) == {"nps", "choice_grid", "long_text"}  # no display blocks
    assert by_type["nps"]["nps"] == {"promoters": 2, "passives": 0, "detractors": 0, "score": 100.0}
    assert by_type["choice_grid"]["grid"][0] == {"row": "Speed", "counts": {"Bad": 0, "OK": 2, "Good": 0}}
    assert all(c["organisation_id"] == 10 and c["form_id"] == form.id for c in calls)
    # counting per value only looks at questions answered from a list
    [counted] = [c for c in calls if c.get("group_by") == ["question_key", "value"]]
    assert counted["question_keys"] == ["k1"]


def test_the_summary_is_scoped_like_results(client, summary_form):
    form, calls = summary_form
    # another organisation's form is not found
    res = client.post("/results/summary", headers=employee_token(id=1, organisation_id=11), json={"form_id": form.id})
    assert res.status_code == 404
    # employees who don't review see nothing
    res = client.post("/results/summary", headers=employee_token(id=2), json={"form_id": form.id})
    assert res.status_code == 403
    # reviewers get their own units only
    res = client.post("/results/summary", json={"form_id": form.id},
                      headers=employee_token(id=2, permissions=["submissions:read"], unit_id=5))
    assert res.status_code == 200 and res.json()["scope"] == "units"
    assert all(c["unit_ids"] == [5] for c in calls)


def test_a_reviewer_without_units_gets_an_empty_summary_without_a_query(client, summary_form):
    form, calls = summary_form
    res = client.post("/results/summary", json={"form_id": form.id},
                      headers=employee_token(id=2, permissions=["submissions:read"]))
    assert res.status_code == 200, res.text
    assert calls == [] and all(q["answered"] == 0 for q in res.json()["questions"])


# ── pictures ─────────────────────────────────────────────────────────────────

def picture(id=5, **overrides) -> StoredFile:
    data = dict(
        id=id, organisation_id=10, purpose="form_media", provider="s3", key=f"k/{id}.webp",
        name=f"{id}.webp", content_type="image/webp", size=100, status="ready",
        attached_type=None, attached_id=None, owner_employee_id=1, form_id=None, variants=None,
    )
    data.update(overrides)
    return StoredFile(**data)


@pytest.fixture
def pictures(monkeypatch):
    store = {f.id: f for f in (
        picture(5), picture(6, attached_type="form", attached_id=40, form_id=40),
        picture(7, organisation_id=11), picture(8, purpose="form_answer"),
        picture(9, attached_type="form", attached_id=99), picture(10, status="pending"),
    )}
    monkeypatch.setattr(files_repo, "get_files", lambda db, ids: {i: store[i] for i in ids if i in store})
    monkeypatch.setattr(files, "signed_link_for", lambda f, **kw: (f"https://cdn/{f.key}", START))
    return store


def test_a_form_may_use_its_own_and_new_pictures(db, pictures):
    files.use_form_media(db, form_id=40, organisation_id=10, file_ids={5, 6})
    assert (pictures[5].attached_type, pictures[5].attached_id, pictures[5].form_id) == ("form", 40, 40)


@pytest.mark.parametrize("file_id", [7, 8, 9, 10, 404])
def test_a_form_may_not_use_other_pictures(db, pictures, file_id):
    with pytest.raises(AppError) as exc:
        files.use_form_media(db, form_id=40, organisation_id=10, file_ids={file_id})
    assert exc.value.code == "files.form_media_invalid"


def test_links_are_only_for_the_organisations_ready_pictures(db, pictures):
    links = files.media_links(db, organisation_id=10, file_ids={5, 6, 7, 8, 10, 404})
    assert set(links) == {"5", "6"}


def test_saving_a_form_attaches_its_pictures(client, monkeypatch, pictures):
    created = []

    def create_form(db, *, data, fields, created_by, before_commit=None):
        form = Form(**data, created_by=created_by, id=41, created_at=START, is_archived=False, is_active=True)
        form.fields = [FormField(id=900 + i, key=f"n{i}", **{k: v for k, v in f.items() if k != "id"})
                       for i, f in enumerate(fields)]
        before_commit(form)
        created.append(form)
        return form

    monkeypatch.setattr(forms_repo, "create_form", create_form)
    monkeypatch.setattr(forms_repo, "form_has_submissions", lambda db, fid: False)
    monkeypatch.setattr(forms_service, "_publish", lambda db, form, eid: None)
    res = client.post("/forms", headers=employee_token(id=1, permissions=["forms:create"]), json={
        "name": "Menu", "type": "questionnaire", "submitter_type": ["customer"],
        "settings": {"theme": {"cover": {"file_id": 5}, "primary_color": "#0F766E"}},
        "fields": [{"question": "Which dish?", "type": "image_choice", "options": ["Soup", "Salad"],
                    "config": {"option_images": [{"file_id": 5}, None]}}],
    })
    assert res.status_code == 201, res.text
    assert pictures[5].attached_id == 41
    body = res.json()
    assert body["media"] == {"5": "https://cdn/k/5.webp"}
    assert body["settings"]["theme"]["primary_color"] == "#0F766E"


def test_saving_a_form_with_another_organisations_picture_is_refused(client, monkeypatch, pictures):
    monkeypatch.setattr(forms_repo, "create_form", lambda db, **kw: kw["before_commit"](
        Form(**kw["data"], id=41, created_by=1)))
    res = client.post("/forms", headers=employee_token(id=1, permissions=["forms:create"]), json={
        "name": "Menu", "type": "questionnaire", "submitter_type": ["customer"],
        "fields": [{"question": "Look", "type": "image", "config": {"image": {"file_id": 7}}}],
    })
    assert res.status_code == 422
    assert pictures[7].attached_type is None


def test_respondents_and_the_public_get_picture_links_and_the_theme(client, monkeypatch, pictures):
    form = form_with(
        field("image", id=1, config={"image": {"file_id": 6}}),
        field("single_choice", id=2, options=["A", "B"], config={"option_images": [{"file_id": 7}, None]}),
        settings={"theme": {"background_color": "#FAFAFA", "cover": {"file_id": 6}}},
    )
    republish(form)
    monkeypatch.setattr(forms_repo, "get_form_by_token", lambda db, t: form if t == "tok" else None)
    res = client.get("/public/forms/tok")
    assert res.status_code == 200, res.text
    body = res.json()
    # picture 7 is another organisation's: named in the config, never linked
    assert body["media"] == {"6": "https://cdn/k/6.webp"}
    assert body["theme"]["background_color"] == "#FAFAFA"
    assert body["fields"][0]["type"] == "image"

    sub = make_submission(form, user_id=2)
    monkeypatch.setattr(subs_repo, "get_submission", lambda db, sid: sub)
    monkeypatch.setattr(subs_repo, "save", lambda db, s: s)
    res = client.get("/submissions/500/form", headers=employee_token(id=2))
    assert res.status_code == 200, res.text
    assert res.json()["media"] == {"6": "https://cdn/k/6.webp"}
    assert res.json()["theme"]["cover"]["file_id"] == 6


def test_a_stored_theme_that_no_longer_fits_is_left_out(client, monkeypatch, pictures):
    form = form_with(field("text"), settings={"theme": {"primary_color": "not a colour"}})
    republish(form)
    monkeypatch.setattr(forms_repo, "get_form_by_token", lambda db, t: form)
    res = client.get("/public/forms/tok")
    assert res.status_code == 200 and res.json()["theme"] is None


def test_duplicating_a_form_copies_its_pictures(client, monkeypatch, pictures):
    form = form_with(field("image", id=1, config={"image": {"file_id": 6}}),
                     settings={"theme": {"cover": {"file_id": 6}}})
    monkeypatch.setattr(forms_repo, "get_form", lambda db, fid: form)
    copied_bytes = []

    class Storage:
        def get_bytes(self, key, **kw):
            return b"img:" + key.encode()

        def put_bytes(self, key, data, **kw):
            copied_bytes.append((key, data))
            return SimpleNamespace(size=len(data), etag="e")

    monkeypatch.setattr(files, "get_storage", lambda provider=None: Storage())
    monkeypatch.setattr(files, "default_provider_name", lambda: "s3")

    def add_file(db, f):
        f.id = 77
        pictures[77] = f
        return f

    monkeypatch.setattr(files_repo, "add_file", add_file)
    made = []

    def create_form(db, *, data, fields, created_by, before_commit=None):
        copy = Form(**data, id=42, created_by=created_by, created_at=START, is_archived=False)
        copy.is_active = data.get("is_active", False)
        copy.fields = [FormField(id=950, key="c", **{k: v for k, v in fields[0].items()})]
        before_commit(copy)
        made.append(copy)
        return copy

    monkeypatch.setattr(forms_repo, "create_form", create_form)
    monkeypatch.setattr(forms_repo, "form_has_submissions", lambda db, fid: False)
    res = client.post(f"/forms/{form.id}/duplicate", headers=employee_token(id=1, permissions=["forms:create"]))
    assert res.status_code in (200, 201), res.text
    [copy] = made
    assert copy.fields[0].config == {"image": {"file_id": 77}}
    assert copy.settings["theme"]["cover"] == {"file_id": 77}
    assert copied_bytes[0][1] == b"img:k/6.webp"
    assert (pictures[77].attached_type, pictures[77].attached_id) == ("form", 42)
    # the original keeps its own picture
    assert form.fields[0].config == {"image": {"file_id": 6}} and pictures[6].attached_id == 40


def test_only_people_who_edit_forms_upload_form_pictures(client, monkeypatch):
    body = {"purpose": "form_media", "name": "menu.png", "content_type": "image/png", "size": 1000}
    res = client.post("/files/uploads", headers=employee_token(id=3), json=body)
    assert res.status_code == 403
    assert res.json()["error"] == "files.form_media_denied"
