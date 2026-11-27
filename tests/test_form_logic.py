"""E2.3: form logic. Questions shown or hidden by rules, section routes on
the same rules, old branching read as routes, and the server checking the
path the browser walked.

modules/forms/logic_cases.json is the contract between the two evaluators:
cx-front runs the same file (e2e/form-logic.spec.ts).
"""

import json
from datetime import datetime, timezone
from pathlib import Path as FsPath
from types import SimpleNamespace

import pytest

from common.errors import AppError
from modules.customers import repository as customers_repo
from modules.forms import behaviour, logic
from modules.forms import repository as forms_repo
from modules.forms import service as forms_service
from modules.forms.model import Form, FormField
from modules.submissions import repository as subs_repo
from modules.submissions.model import Submission
from tests.conftest import employee_token, make_form, make_submission, republish
from tests.test_form_versions import edit, live, versions  # noqa: F401  (fixtures)

CASES = json.loads((FsPath(logic.__file__).parent / "logic_cases.json").read_text(encoding="utf-8"))
CREATOR = employee_token(id=1, permissions=["forms:create"])
DETAILS = {"email": "ann@acme.io", "first_name": "Ann", "last_name": "Lee"}


def field_of(data: dict) -> SimpleNamespace:
    base = {"key": f"k{data['id']}" if "id" in data else None, "type": "single_choice", "order": 0,
            "section_id": None, "visible_if": None, "branching": None, "config": None}
    return SimpleNamespace(**{**base, **data})


def same(actual, expected) -> bool:
    """JSON equality where 3 matches 3.0 but true never matches 1."""
    if isinstance(expected, bool) or isinstance(actual, bool):
        return type(actual) is type(expected) and actual == expected
    if isinstance(expected, (int, float)) and isinstance(actual, (int, float)):
        return actual == expected
    if isinstance(expected, list):
        return isinstance(actual, list) and len(actual) == len(expected) and all(
            same(a, e) for a, e in zip(actual, expected))
    if isinstance(expected, dict):
        return isinstance(actual, dict) and actual.keys() == expected.keys() and all(
            same(actual[k], expected[k]) for k in expected)
    return type(actual) is type(expected) and actual == expected


# ── the shared cases ──────────────────────────────────────────────────────────

def test_case_names_are_unique():
    names = [c["name"] for c in CASES["values"]] + [c["name"] for c in CASES["paths"]]
    assert len(names) == len(set(names))


@pytest.mark.parametrize("case", CASES["values"], ids=lambda c: c["name"])
def test_answer_values(case):
    got = logic.answer_value(field_of(case["field"]), case["raw"])
    assert same(got, case["value"]), got


@pytest.mark.parametrize("case", CASES["paths"], ids=lambda c: c["name"])
def test_paths(case):
    form = SimpleNamespace(
        sections=case["form"].get("sections"),
        fields=[field_of(f) for f in case["form"]["fields"]],
    )
    path = logic.walk(form, case["answers"], case.get("hidden"))
    assert path.sections == case["sections"]
    assert sorted(path.shown) == sorted(case["shown"])


def test_the_walk_gives_the_same_path_on_the_answers_it_kept():
    """A finished response keeps only answers its path showed; walking those
    again gives the same path (the detail view and regrades rely on it)."""
    for case in CASES["paths"]:
        form = SimpleNamespace(sections=case["form"].get("sections"),
                               fields=[field_of(f) for f in case["form"]["fields"]])
        first = logic.walk(form, case["answers"], case.get("hidden"))
        kept = {k: v for k, v in case["answers"].items() if int(k) in first.shown}
        again = logic.walk(form, kept, case.get("hidden"))
        assert (again.sections, again.shown) == (first.sections, first.shown), case["name"]


# ── checks on save ────────────────────────────────────────────────────────────

def rows(*fields):
    return [{"key": f"k{i}", "type": "text", "order": i, "question": f"Q{i}", **f} for i, f in enumerate(fields)]


def code_of(fn) -> str:
    with pytest.raises(AppError) as err:
        fn()
    return err.value.code


def test_a_rule_reading_an_earlier_question_is_accepted():
    logic.validate_logic("questionnaire", None, rows({}, {"visible_if": {"==": [{"var": "q.k0"}, "x"]}}))


@pytest.mark.parametrize("rule, code", [
    ({"==": [{"var": "q.k1"}, "x"]}, "forms.rule_reads_later_question"),  # itself
    ({"==": [{"var": "q.k2"}, "x"]}, "forms.rule_reads_later_question"),  # a later one
    ({"==": [{"var": "q.nope"}, "x"]}, "forms.rule_reads_later_question"),
    ({"==": [{"var": {"if": [True, "q.k0", "q.k2"]}}, "x"]}, "forms.rule_dynamic_reference"),
    ({"==": [{"var": "answers.1"}, "x"]}, "forms.rule_unknown_reference"),
    ({"==": [{"var": ""}, "x"]}, "forms.rule_unknown_reference"),
    ({"==": [{"var": "q.k0.1"}, "x"]}, "forms.rule_unknown_reference"),  # a row of a text question
    ({"==": [{"var": "hidden.channel"}, "x"]}, "forms.rule_unknown_hidden"),
    ({"nope": [1]}, "forms.rule_invalid"),
])
def test_bad_rules_are_refused(rule, code):
    fields = rows({}, {"visible_if": rule}, {})
    assert code_of(lambda: logic.validate_logic("questionnaire", None, fields)) == code


def test_a_rule_can_read_a_declared_hidden_value():
    fields = rows({"visible_if": {"==": [{"var": "hidden.channel"}, "x"]}})
    logic.validate_logic("questionnaire", None, fields, {"channel"})


def test_a_rule_reads_answers_not_display_blocks():
    fields = rows({"type": "heading"}, {"visible_if": {"empty": {"var": "q.k0"}}})
    assert code_of(lambda: logic.validate_logic("questionnaire", None, fields)) == "forms.rule_reads_later_question"


def test_a_grid_row_can_be_read():
    fields = rows({"type": "likert"}, {"visible_if": {"==": [{"var": "q.k0.2"}, "Agree"]}})
    logic.validate_logic("questionnaire", None, fields)


def test_rules_are_for_questionnaires():
    fields = rows({}, {"visible_if": {"==": [{"var": "q.k0"}, "x"]}})
    assert code_of(lambda: logic.validate_logic("exam", None, fields)) == "forms.logic_questionnaires_only"


SECTIONS = [{"id": 1, "order": 0, "title": "One"}, {"id": 2, "order": 1, "title": "Two"},
            {"id": 3, "order": 2, "title": "Three"}]


def with_routes(section_id, routes):
    return [{**s, "routes": routes} if s["id"] == section_id else s for s in SECTIONS]


def test_routes_read_their_section_and_earlier_ones():
    fields = rows({"section_id": 1}, {"section_id": 2})
    logic.validate_logic("questionnaire", with_routes(2, [
        {"when": {"and": [{"var": "q.k0"}, {"var": "q.k1"}]}, "to": "end"},
    ]), fields)


@pytest.mark.parametrize("route, code", [
    ({"when": {"var": "q.k1"}, "to": 3}, "forms.rule_reads_later_question"),  # a later section
    ({"when": True, "to": 1}, "forms.branching_backwards"),
    ({"when": True, "to": 9}, "forms.branching_unknown_target"),
    ({"when": {"var": [{"var": "x"}]}, "to": 3}, "forms.rule_dynamic_reference"),
])
def test_bad_routes_are_refused(route, code):
    fields = rows({"section_id": 1}, {"section_id": 2})
    assert code_of(lambda: logic.validate_logic("questionnaire", with_routes(1, [route]), fields)) == code


def test_routes_are_for_questionnaires():
    sections = with_routes(1, [{"when": True, "to": "end"}])
    assert code_of(lambda: logic.validate_logic("exam", sections, [])) == "forms.branching_questionnaires_only"


def test_too_many_routes():
    sections = with_routes(1, [{"when": False, "to": "end"}] * (logic.MAX_ROUTES + 1))
    assert code_of(lambda: logic.validate_logic("questionnaire", sections, [])) == "forms.too_many_routes"


def test_two_questions_cant_share_a_key():
    fields = rows({}, {"visible_if": True})
    fields[1]["key"] = "k0"
    assert code_of(lambda: logic.validate_logic("questionnaire", None, fields)) == "forms.duplicate_field_keys"


def test_rewriting_keys_follows_every_reference():
    rule = {"and": [{"==": [{"var": "q.old"}, 1]}, {"==": [{"var": ["q.old.2", 0]}, "x"]},
                    {"var": "q.other"}, {"var": "hidden.old"}]}
    assert logic.rewrite_keys(rule, {"old": "new"}) == {"and": [
        {"==": [{"var": "q.new"}, 1]}, {"==": [{"var": ["q.new.2", 0]}, "x"]},
        {"var": "q.other"}, {"var": "hidden.old"},
    ]}


# ── saving forms ──────────────────────────────────────────────────────────────

@pytest.fixture
def created(monkeypatch):
    """Stubs repository.create_form like the real one: each row's key is kept."""
    saved = {}

    def create_form(db, *, data, fields, created_by, before_commit=None):
        form = Form(**data, created_by=created_by)
        form.id, form.is_active, form.is_archived = 70, False, False
        form.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        form.fields = [FormField(id=900 + i, **{k: v for k, v in f.items() if k != "id"})
                       for i, f in enumerate(fields)]
        saved["form"] = form
        return form

    monkeypatch.setattr(forms_repo, "create_form", create_form)
    monkeypatch.setattr(forms_repo, "form_has_submissions", lambda db, fid: False)
    return saved


def post(client, fields, sections=None, form_type="questionnaire", settings=None):
    body = {"name": "Survey", "type": form_type, "submitter_type": ["customer"], "is_active": False,
            "fields": fields}
    if sections is not None:
        body["sections"] = sections
    if settings is not None:
        body["settings"] = settings
    return client.post("/forms", headers=CREATOR, json=body)


KEY_A = "a" * 32
KEY_B = "b" * 32


def test_a_new_form_can_name_its_new_questions(client, created):
    res = post(client, [
        {"key": KEY_A, "question": "Happy?", "type": "boolean", "order": 0},
        {"key": KEY_B, "question": "Why not?", "type": "text", "order": 1,
         "visible_if": {"==": [{"var": f"q.{KEY_A}"}, False]}},
    ])
    assert res.status_code == 201, res.text
    fields = res.json()["fields"]
    assert [f["key"] for f in fields] == [KEY_A, KEY_B]
    assert fields[1]["visible_if"] == {"==": [{"var": f"q.{KEY_A}"}, False]}


def test_questions_without_a_key_get_one(client, created):
    res = post(client, [{"question": "Q", "type": "text"}])
    assert res.status_code == 201
    assert len(res.json()["fields"][0]["key"]) == 32


def test_a_rule_reading_a_later_question_is_refused(client, created):
    res = post(client, [
        {"key": KEY_A, "question": "First", "type": "text", "order": 0,
         "visible_if": {"==": [{"var": f"q.{KEY_B}"}, "x"]}},
        {"key": KEY_B, "question": "Second", "type": "text", "order": 1},
    ])
    assert res.status_code == 422
    assert res.json()["error"] == "forms.rule_reads_later_question"
    assert "form" not in created


def test_a_bad_key_is_refused(client, created):
    res = post(client, [{"key": "has.dot", "question": "Q", "type": "text"}])
    assert res.status_code == 422


def test_rules_on_an_exam_are_refused(client, created):
    res = post(client, [
        {"key": KEY_A, "question": "First", "type": "single_choice", "options": ["A", "B"],
         "right_answer": "A", "score_weight": 1, "order": 0},
        {"key": KEY_B, "question": "Second", "type": "text", "order": 1,
         "visible_if": {"==": [{"var": f"q.{KEY_A}"}, "B"]}},
    ], form_type="exam")
    assert res.status_code == 422 and res.json()["error"] == "forms.logic_questionnaires_only"


def test_rules_may_read_declared_hidden_fields(client, created):
    fields = [{"question": "For branch visitors", "type": "text",
               "visible_if": {"==": [{"var": "hidden.channel"}, "branch"]}}]
    assert post(client, fields).json()["error"] == "forms.rule_unknown_hidden"
    res = post(client, fields, settings={"hidden_fields": [{"key": "channel"}]})
    assert res.status_code == 201, res.text


def test_old_branching_is_saved_as_routes(client, created):
    res = post(client, [
        {"key": KEY_A, "question": "Pick", "type": "single_choice", "options": ["A", "B"],
         "section_id": 1, "branching": {"B": 3}},
        {"question": "Two", "type": "text", "section_id": 2},
    ], sections=[{"id": 1, "title": "One", "order": 0}, {"id": 2, "title": "Two", "order": 1},
                 {"id": 3, "title": "Three", "order": 2}])
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["sections"][0]["routes"] == [{"when": {"==": [{"var": f"q.{KEY_A}"}, "B"]}, "to": 3}]
    assert body["sections"][1]["routes"] is None
    assert all(f["branching"] is None for f in body["fields"])


def test_routes_are_saved_with_their_sections(client, created):
    routes = [{"when": {">=": [{"var": f"q.{KEY_A}"}, 9]}, "to": "end"}]
    res = post(client, [
        {"key": KEY_A, "question": "Score", "type": "nps", "section_id": 1},
    ], sections=[{"id": 1, "title": "One", "order": 0, "routes": routes},
                 {"id": 2, "title": "Two", "order": 1}])
    assert res.status_code == 201, res.text
    assert res.json()["sections"][0]["routes"] == routes


def test_a_route_needs_a_target_and_a_rule(client, created):
    res = post(client, [{"question": "Q", "type": "text", "section_id": 1}],
               sections=[{"id": 1, "title": "One", "routes": [{"to": "end"}]}])
    assert res.status_code == 422


def test_changing_a_questions_type_gives_it_a_new_key_and_rules_follow(client, live):
    live.fields.append(FormField(
        id=103, key="k103", question="Follow-up", type="text", order=2, is_required=False,
        score_weight=0.0, section_id=1, visible_if={"==": [{"var": "q.k101"}, "B"]},
    ))
    res = edit(client, live, {
        101: {"type": "dropdown", "options": ["A", "B"]},
        103: {"visible_if": {"==": [{"var": "q.k101"}, "B"]}},
    })
    assert res.status_code == 200, res.text
    by_id = {f["id"]: f for f in res.json()["fields"]}
    new_key = by_id[101]["key"]
    assert new_key != "k101"
    assert by_id[103]["visible_if"] == {"==": [{"var": f"q.{new_key}"}, "B"]}


def test_an_edit_with_old_branching_saves_routes(client, live):
    res = edit(client, live, {101: {"branching": {"B": "end"}}})
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["sections"][0]["routes"] == [{"when": {"==": [{"var": "q.k101"}, "B"]}, "to": "end"}]
    assert {f["branching"] for f in body["fields"]} == {None}


def test_a_new_question_cant_take_an_existing_key(client, live):
    fields = [{"id": f.id, "question": f.question, "type": f.type, "options": f.options,
               "right_answer": f.right_answer, "order": f.order, "is_required": f.is_required,
               "score_weight": f.score_weight, "section_id": f.section_id} for f in live.fields]
    fields.append({"key": "k101", "question": "Copycat", "type": "text", "section_id": 1, "order": 5})
    res = client.patch(f"/forms/{live.id}", headers=employee_token(id=1), json={"fields": fields, "sections": live.sections})
    assert res.status_code == 422 and res.json()["error"] == "forms.field_key_taken", res.text


def test_two_new_questions_cant_share_a_key(client, live):
    """Without rules on the form too: the unique (form_id, key) index would
    otherwise turn it into a 500."""
    fields = [{"id": f.id, "question": f.question, "type": f.type, "options": f.options,
               "right_answer": f.right_answer, "order": f.order, "is_required": f.is_required,
               "score_weight": f.score_weight, "section_id": f.section_id} for f in live.fields]
    fields += [{"key": "twin", "question": f"Twin {i}", "type": "text", "section_id": 1, "order": 5 + i}
               for i in range(2)]
    res = client.patch(f"/forms/{live.id}", headers=employee_token(id=1), json={"fields": fields, "sections": live.sections})
    assert res.status_code == 422 and res.json()["error"] == "forms.field_key_taken", res.text


def test_old_branching_and_the_routes_it_means_are_the_same_version(live):
    """A form saved once (its branching now routes) has nothing new to publish."""
    snapshot = forms_service.snapshot_of(live)
    old = json.loads(json.dumps(snapshot))
    old["fields"][0]["branching"] = {"B": "end"}
    new = json.loads(json.dumps(snapshot))
    new["sections"][0]["routes"] = [{"when": {"==": [{"var": "q.k101"}, "B"]}, "to": "end"}]
    assert forms_service._comparable(old) == forms_service._comparable(new)


def test_duplicating_keeps_keys_and_rules(client, monkeypatch):
    form = make_form(type="questionnaire")
    form.fields[1].visible_if = {"==": [{"var": "q.k101"}, "B"]}
    form.sections[0]["routes"] = [{"when": {"var": "q.k101"}, "to": "end"}]
    monkeypatch.setattr(forms_repo, "get_form", lambda db, fid: form if fid == form.id else None)
    copied = {}

    def create_form(db, *, data, fields, created_by, before_commit=None):
        copied.update(data=data, fields=fields)
        copy = Form(**data, id=42, created_by=created_by, created_at=form.created_at, is_archived=False)
        copy.fields = [FormField(id=950 + i, **f) for i, f in enumerate(fields)]
        return copy

    monkeypatch.setattr(forms_repo, "create_form", create_form)
    monkeypatch.setattr(forms_repo, "form_has_submissions", lambda db, fid: False)
    res = client.post(f"/forms/{form.id}/duplicate", headers=employee_token(id=1))
    assert res.status_code in (200, 201), res.text
    assert [f["key"] for f in copied["fields"]] == ["k101", "k102"]
    assert copied["fields"][1]["visible_if"] == {"==": [{"var": "q.k101"}, "B"]}
    assert copied["data"]["sections"][0]["routes"] == [{"when": {"var": "q.k101"}, "to": "end"}]


# ── answering: the server checks the path ─────────────────────────────────────

def logic_form(**overrides) -> Form:
    """A public questionnaire: 101 (A/B, required) and, when 101 is B, a
    required graded follow-up 103, in section 1; 102 (text) in section 2."""
    form = make_form(type="questionnaire", published=False, max_attempts=None, **overrides)
    form.fields.append(FormField(
        id=103, key="k103", question="Why B?", type="single_choice", options=["X", "Y"],
        right_answer="Y", order=2, help_text=None, is_required=True, score_weight=1.0,
        section_id=1, branching=None, visible_if={"==": [{"var": "q.k101"}, "B"]},
    ))
    republish(form)
    return form


@pytest.fixture
def public_logic(monkeypatch):
    form = logic_form()
    monkeypatch.setattr(forms_repo, "get_form_by_token", lambda db, t: form if t == "tok" else None)
    monkeypatch.setattr(subs_repo, "count_finalized_attempts", lambda db, **kw: 0)
    monkeypatch.setattr(customers_repo, "get_by_email", lambda db, **kw: None)
    return form


def submit(client, answers, **extra):
    return client.post("/public/forms/tok/submit", json={"customer": DETAILS, "answers": answers, **extra})


def stored(db) -> Submission:
    return next(o for o in db.added if isinstance(o, Submission))


def test_a_hidden_questions_answer_is_dropped_and_not_required(client, db, public_logic):
    res = submit(client, {"101": "A", "102": "physics", "103": "Y"})
    assert res.status_code == 201, res.text
    assert stored(db).answers == {"101": "A", "102": "physics"}


def test_a_shown_required_question_must_be_answered(client, db, public_logic):
    res = submit(client, {"101": "B", "102": "physics"})
    assert res.status_code == 422
    assert res.json()["error"] == "submissions.field_required"


def test_a_hidden_question_isnt_graded(client, db, public_logic):
    # section 1: 101 right (103 hidden, so not counted) = 100; section 2:
    # text graded 0.5 (stub) = 50; weights 1 and 3
    assert submit(client, {"101": "A", "102": "physics"}).status_code == 201
    assert stored(db).score == pytest.approx(0.25 * 100 + 0.75 * 50)
    rows = [o for o in db.added if type(o).__name__ == "SubmissionValue"]
    assert sorted(r.field_id for r in rows) == [101, 102]


def test_a_shown_question_is_graded(client, db, public_logic):
    assert submit(client, {"101": "B", "102": "physics", "103": "X"}).status_code == 201
    # section 1: 101 wrong, 103 wrong = 0
    assert stored(db).score == pytest.approx(0.75 * 50)


def test_routes_skip_sections_on_the_server(client, db, monkeypatch):
    form = make_form(type="questionnaire", published=False, max_attempts=None)
    form.sections[0]["routes"] = [{"when": {"==": [{"var": "q.k101"}, "A"]}, "to": "end"}]
    form.fields[1].is_required = True
    republish(form)
    monkeypatch.setattr(forms_repo, "get_form_by_token", lambda db, t: form if t == "tok" else None)
    monkeypatch.setattr(subs_repo, "count_finalized_attempts", lambda db, **kw: 0)
    monkeypatch.setattr(customers_repo, "get_by_email", lambda db, **kw: None)
    res = submit(client, {"101": "A", "102": "on a skipped section"})
    assert res.status_code == 201, res.text
    assert stored(db).answers == {"101": "A"}


def prefill_for(form, **hidden) -> str:
    return behaviour.prefill_token(form.id, hidden=hidden, answers={}, expires_at=None)


@pytest.fixture
def hidden_logic(monkeypatch):
    """101 is shown only to visitors whose link says channel=branch."""
    form = make_form(type="questionnaire", published=False, max_attempts=None)
    form.settings = {"hidden_fields": [{"key": "channel"}, {"key": "staff"}]}
    form.fields[0].visible_if = {"==": [{"var": "hidden.channel"}, "branch"]}
    republish(form)
    monkeypatch.setattr(forms_repo, "get_form_by_token", lambda db, t: form if t == "tok" else None)
    monkeypatch.setattr(subs_repo, "count_finalized_attempts", lambda db, **kw: 0)
    monkeypatch.setattr(customers_repo, "get_by_email", lambda db, **kw: None)
    return form


def test_hidden_values_from_the_link_decide_on_the_server(client, db, hidden_logic):
    # without the link 101 is hidden, so it isn't required
    assert submit(client, {"102": "x"}).status_code == 201
    db.added.clear()
    link = prefill_for(hidden_logic, channel="branch")
    assert submit(client, {"102": "x"}, prefill=link).json()["error"] == "submissions.field_required"
    assert submit(client, {"101": "A", "102": "x"}, prefill=link).status_code == 201


def test_respondents_get_rules_routes_and_only_the_hidden_values_rules_read(client, hidden_logic):
    hidden_logic.fields[1].branching = None
    link = prefill_for(hidden_logic, channel="branch", staff="Mona")
    body = client.get(f"/public/forms/tok?prefill={link}").json()
    assert body["hidden"] == {"channel": "branch"}
    by_id = {f["id"]: f for f in body["fields"]}
    assert by_id[101]["key"] == "k101"
    assert by_id[101]["visible_if"] == {"==": [{"var": "hidden.channel"}, "branch"]}
    assert "branching" not in by_id[101]
    assert [s["routes"] for s in body["sections"]] == [[], []]


def test_respondents_get_old_branching_as_routes(client, monkeypatch):
    form = make_form(type="questionnaire", published=False)
    form.fields[0].branching = {"B": "end"}
    republish(form)
    monkeypatch.setattr(forms_repo, "get_form_by_token", lambda db, t: form if t == "tok" else None)
    body = client.get("/public/forms/tok").json()
    assert body["sections"][0]["routes"] == [{"when": {"==": [{"var": "q.k101"}, "B"]}, "to": "end"}]
    assert body["hidden"] == {}


def test_employees_get_the_hidden_values_their_attempt_started_with(client, monkeypatch):
    form = make_form(type="questionnaire", published=False)
    form.settings = {"hidden_fields": [{"key": "channel"}, {"key": "staff"}]}
    form.fields[1].visible_if = {"==": [{"var": "hidden.channel"}, "branch"]}
    republish(form)
    sub = make_submission(form, hidden_fields={"channel": "branch", "staff": "Mona"})
    monkeypatch.setattr(subs_repo, "get_submission", lambda db, sid: sub if sid == sub.id else None)
    res = client.get("/submissions/500/form", headers=employee_token(id=2))
    assert res.status_code == 200, res.text
    assert res.json()["hidden"] == {"channel": "branch"}


def test_the_detail_view_marks_hidden_questions_skipped(monkeypatch):
    from modules.submissions import service as subs_service

    form = logic_form()
    sub = make_submission(form, status="submitted", answers={"101": "A", "102": "x"},
                          submitted_at=datetime(2026, 1, 1, tzinfo=timezone.utc))
    detail = subs_service.serialize_detail(sub, principal=_owner())
    skipped = {f.id: f.skipped for f in detail.fields}
    assert skipped == {101: False, 102: False, 103: True}


def _owner():
    from modules.auth.dto import EmployeePrincipal

    return EmployeePrincipal(id=2, jti="j", organisation_id=10)


def test_a_question_resent_without_its_rule_keeps_it(client, live):
    rule = {"==": [{"var": "q.k101"}, "B"]}
    live.fields[1].visible_if = rule
    live.sections[0]["routes"] = [{"when": {"var": "q.k101"}, "to": "end"}]
    res = edit(client, live, {101: {"question": "Reworded"}})  # sends neither
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["fields"][1]["visible_if"] == rule
    assert body["sections"][0]["routes"] == [{"when": {"var": "q.k101"}, "to": "end"}]


def test_a_rule_can_be_removed_by_sending_null(client, live):
    live.fields[1].visible_if = {"==": [{"var": "q.k101"}, "B"]}
    live.sections[0]["routes"] = [{"when": {"var": "q.k101"}, "to": "end"}]
    sections = [{**s, "routes": None} for s in live.sections]
    fields = [{"id": f.id, "question": f.question, "type": f.type, "options": f.options,
               "right_answer": f.right_answer, "order": f.order, "is_required": f.is_required,
               "score_weight": f.score_weight, "section_id": f.section_id, "visible_if": None}
              for f in live.fields]
    res = client.patch(f"/forms/{live.id}", headers=employee_token(id=1), json={"fields": fields, "sections": sections})
    assert res.status_code == 200, res.text
    assert res.json()["fields"][1]["visible_if"] is None
    assert res.json()["sections"][0]["routes"] is None
