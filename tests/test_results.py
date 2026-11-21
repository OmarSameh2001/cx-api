"""E1.6: one row per answer, score breakdowns, regrading, and the results
query with its organisation and unit scoping."""

from datetime import date, datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from sqlalchemy.dialects import postgresql

from common.worker.registry import JOBS
from modules.employees.model import Employee
from modules.forms import repository as forms_repo
from modules.forms.model import Form, FormField
from modules.results import repository as results_repo
from modules.results import service as results_service
from modules.results.model import SubmissionValue
from modules.submissions import repository as subs_repo
from modules.submissions import service as subs_service
from modules.submissions.model import Submission
from tests.conftest import customer_token, employee_token, make_form, make_submission, republish

START = datetime(2026, 3, 1, 9, 0, tzinfo=timezone.utc)


def values(db) -> list[SubmissionValue]:
    return [o for o in db.added if isinstance(o, SubmissionValue)]


@pytest.fixture
def exam(monkeypatch):
    form = make_form()
    monkeypatch.setattr(forms_repo, "get_form", lambda db, fid: form if fid == form.id else None)
    monkeypatch.setattr(forms_repo, "get_form_by_token", lambda db, t: form if t == "tok" else None)
    return form


@pytest.fixture
def attempt(exam, monkeypatch):
    sub = make_submission(exam, started_at=START)
    monkeypatch.setattr(subs_repo, "get_submission", lambda db, sid: sub if sid == sub.id else None)
    monkeypatch.setattr(subs_repo, "save", lambda db, s: s)
    return sub


def survey(**overrides) -> Form:
    """A questionnaire with one question of every type, no sections."""
    form = make_form(published=False, type="questionnaire", sections=None, time_limit_minutes=None,
                     max_attempts=None, **overrides)
    kinds = [
        ("single_choice", ["Good", "Bad"], "Good", 2.0),
        ("multi_choice", ["Price", "Speed", "Staff"], "Price,Speed", 1.0),
        ("boolean", None, "true", 1.0),
        ("scale", None, None, 0.0),
        ("text", None, None, 0.0),
        ("date", None, None, 0.0),
        ("email", None, None, 0.0),
        ("file", None, None, 0.0),
    ]
    form.fields = [
        FormField(id=200 + i, key=f"k{200 + i}", question=t, type=t, options=opts, right_answer=right,
                  order=i, is_required=False, score_weight=w, section_id=None)
        for i, (t, opts, right, w) in enumerate(kinds)
    ]
    republish(form)
    return form


# ── grading ──────────────────────────────────────────────────────────────────

def test_grade_breaks_the_score_down_by_section_and_question(exam):
    result = subs_service.grade(exam, {"101": "A", "102": "physics"}, {1, 2})
    # sections weigh 1 and 3; the text answer scores 0.5 in tests
    assert result.total == pytest.approx(62.5)
    assert result.total == subs_service._score(exam, {"101": "A", "102": "physics"}, {1, 2})
    assert result.sections == [
        {"id": 1, "score": 100.0, "weight": 1.0},
        {"id": 2, "score": 50.0, "weight": 3.0},
    ]
    assert result.questions == {101: (1.0, 1.0), 102: (0.5, 1.0)}
    assert result.as_json(exam)["questions"] == [
        {"field_id": 101, "key": "k101", "score": 1.0, "max": 1.0},
        {"field_id": 102, "key": "k102", "score": 0.5, "max": 1.0},
    ]


def test_sections_off_the_path_are_not_in_the_breakdown(exam):
    result = subs_service.grade(exam, {"101": "B"}, {1})
    assert result.total == 0.0
    assert result.sections == [{"id": 1, "score": 0.0, "weight": 1.0}]
    assert result.questions == {101: (0.0, 1.0)}


def test_unweighted_questions_are_not_graded(monkeypatch):
    form = survey()
    calls = []
    monkeypatch.setattr(subs_service, "score_text", lambda a, r: calls.append(a) or 1.0)
    result = subs_service.grade(form, {"200": "Good", "204": "anything"})
    assert set(result.questions) == {200, 201, 202}  # the weighted ones
    assert calls == []  # the weight-0 text answer never reached the similarity model
    assert result.sections == []


def test_a_form_without_graded_questions_scores_zero_with_an_empty_breakdown():
    form = survey()
    for f in form.fields:
        f.score_weight = 0.0
    republish(form)
    result = subs_service.grade(form, {"200": "Good"})
    assert (result.total, result.sections, result.questions) == (0.0, [], {})


# ── rows on submit ───────────────────────────────────────────────────────────

def test_submitting_writes_one_row_per_answer_with_score_and_unit(client, db, attempt):
    res = client.post(f"/submissions/{attempt.id}/submit",
                      headers=employee_token(id=2, unit_id=31),
                      json={"answers": {"101": "A", "102": "Because"}})
    assert res.status_code == 200, res.text
    assert attempt.score == pytest.approx(62.5)
    assert attempt.scores["total"] == pytest.approx(62.5)
    assert [s["id"] for s in attempt.scores["sections"]] == [1, 2]

    rows = values(db)
    assert [(r.field_id, r.question_key, r.question_type) for r in rows] == [
        (101, "k101", "single_choice"), (102, "k102", "text"),
    ]
    first, second = rows
    assert (first.value_text, first.score, first.max_score) == ("A", 1.0, 1.0)
    assert (second.value_text, second.score) == ("Because", 0.5)
    for r in rows:
        assert r.submission_id == attempt.id
        assert (r.organisation_id, r.form_id, r.form_version_id) == (10, 7, attempt.form_version_id)
        assert r.unit_id == 31  # the respondent's unit, from their token
        assert r.subject_employee_id is None
        assert r.submitted_at == attempt.submitted_at
        assert r.duration_seconds == int((attempt.submitted_at - START).total_seconds())


def test_unanswered_and_skipped_questions_have_no_row(client, db, attempt, exam):
    exam.fields[0].branching = {"B": "end"}  # answering B skips section 2
    republish(exam)
    attempt.form_version = exam.current_version
    res = client.post(f"/submissions/{attempt.id}/submit", headers=employee_token(id=2),
                      json={"answers": {"101": "B", "102": "dropped: section 2 was skipped"}})
    assert res.status_code == 200, res.text
    assert [r.field_id for r in values(db)] == [101]
    assert values(db)[0].unit_id is None  # an employee without a unit


def test_a_rejected_submit_writes_no_rows(client, db, attempt):
    res = client.post(f"/submissions/{attempt.id}/submit", headers=employee_token(id=2),
                      json={"answers": {"101": "not an option"}})
    assert res.status_code == 422
    assert values(db) == []


def test_public_submissions_get_rows_without_unit_or_duration(client, db, exam, monkeypatch):
    from modules.customers import repository as customers_repo

    exam.type = "questionnaire"
    monkeypatch.setattr(customers_repo, "get_by_email", lambda db, **kw: None)
    monkeypatch.setattr(subs_repo, "count_finalized_attempts", lambda db, **kw: 0)
    res = client.post("/public/forms/tok/submit", json={
        "customer": {"email": "ann@acme.io", "first_name": "Ann", "last_name": "Lee"},
        "answers": {"101": "A"},
    })
    assert res.status_code == 201, res.text
    sub = next(o for o in db.added if isinstance(o, Submission))
    [row] = values(db)
    assert row.submission_id == sub.id is not None
    assert (row.value_text, row.unit_id, row.duration_seconds) == ("A", None, None)
    # both sections are on the path; the unanswered text question scores 0
    assert sub.score == pytest.approx(25.0)
    assert sub.scores["sections"] == [{"id": 1, "score": 100.0, "weight": 1.0},
                                      {"id": 2, "score": 0.0, "weight": 3.0}]


def test_every_question_type_lands_in_its_column():
    form = survey()
    sub = make_submission(form, status="submitted", submitted_at=START, answers={
        "200": "Good",
        "201": ["Price", "Speed"],
        "202": "true",
        "203": "4",
        "204": "Friendly staff",
        "205": "2026-02-28",
        "206": "ann@acme.io",
        "207": {"file_id": 9, "name": "r.pdf", "content_type": "application/pdf", "size": 10},
    })
    rows = {r.question_type: r for r in results_service.build_values(sub, form, {}, unit_id=None)}
    assert rows["single_choice"].value_text == "Good"
    assert rows["multi_choice"].value_json == ["Price", "Speed"]
    assert rows["boolean"].value_bool is True
    assert rows["scale"].value_number == 4.0
    assert rows["text"].value_text == "Friendly staff"
    assert rows["date"].value_date == date(2026, 2, 28)
    assert rows["email"].value_text == "ann@acme.io"
    assert rows["file"].value_json["file_id"] == 9
    for r in rows.values():
        assert r.score is None and r.max_score is None  # no grading given


@pytest.mark.parametrize("field_type, value, column, stored", [
    ("multi_choice", "Price, Speed", "value_json", ["Price", "Speed"]),  # older comma form
    ("boolean", False, "value_bool", False),
    ("scale", 3, "value_number", 3.0),
    # older answers that don't fit their type are kept, not dropped
    ("scale", "lots", "value_json", "lots"),
    ("date", "28/02/2026", "value_json", "28/02/2026"),
    ("boolean", "maybe", "value_json", "maybe"),
    ("single_choice", 5, "value_json", 5),
])
def test_values_are_typed_and_odd_old_answers_are_kept(field_type, value, column, stored):
    assert results_service._typed(field_type, value) == {column: stored}


@pytest.mark.parametrize("empty", [None, "", [], {}])
def test_empty_answers_have_no_row(empty):
    form = survey()
    sub = make_submission(form, status="submitted", submitted_at=START, answers={"200": empty})
    assert results_service.build_values(sub, form, {}, unit_id=None) == []


# ── regrading ────────────────────────────────────────────────────────────────

@pytest.fixture
def finished(exam, db, monkeypatch):
    deleted = []
    monkeypatch.setattr(results_repo, "delete_values", lambda db, sid: deleted.append(sid))
    sub = make_submission(exam, status="submitted", submitted_at=START + timedelta(minutes=5),
                          started_at=START, answers={"101": "A", "102": "Because"}, score=62.5)
    sub.employee = Employee(id=2, unit_id=44)
    return SimpleNamespace(sub=sub, deleted=deleted)


def test_regrade_rewrites_the_rows(db, finished):
    assert subs_service.regrade_submission(db, finished.sub, update_score=False) == "same"
    assert finished.deleted == [finished.sub.id]
    assert [(r.field_id, r.unit_id, r.duration_seconds) for r in values(db)] == [(101, 44, 300), (102, 44, 300)]
    assert finished.sub.scores["total"] == pytest.approx(62.5)


def test_regrade_keeps_a_different_stored_score_unless_asked(db, finished):
    finished.sub.score = 80.0  # scored by older rules
    assert subs_service.regrade_submission(db, finished.sub, update_score=False) == "differs"
    assert finished.sub.score == 80.0 and finished.sub.scores is None
    assert len(values(db)) == 2  # the rows are written all the same

    assert subs_service.regrade_submission(db, finished.sub, update_score=True) == "changed"
    assert finished.sub.score == pytest.approx(62.5)
    assert finished.sub.scores["total"] == pytest.approx(62.5)


def test_regrade_uses_the_version_answered(db, finished, exam):
    exam.fields[0].right_answer = "B"  # a later version marks A wrong
    republish(exam)
    assert subs_service.regrade_submission(db, finished.sub, update_score=False) == "same"


def test_rebuild_walks_every_finished_submission_in_batches(db, finished, monkeypatch):
    batches = [[finished.sub], []]
    calls = []

    def finalized_after(db, *, after_id, form_id, limit):
        calls.append((after_id, form_id, limit))
        return batches.pop(0)

    monkeypatch.setattr(subs_repo, "finalized_after", finalized_after)
    counts = subs_service.rebuild_results(db, form_id=7, batch_size=50)
    assert counts == {"same": 1, "changed": 0, "differs": 0}
    assert calls == [(0, 7, 50), (finished.sub.id, 7, 50)]
    assert db.commits == 1


def test_rebuild_is_a_background_job():
    job = JOBS["results.rebuild"]
    assert job.every_seconds is None  # dispatched, never scheduled


# ── the detail view ──────────────────────────────────────────────────────────

def test_the_breakdown_is_shown_with_the_score(client, exam, monkeypatch):
    sub = make_submission(exam, status="submitted", submitted_at=START, score=62.5,
                          scores={"total": 62.5, "sections": [], "questions": []})
    monkeypatch.setattr(subs_repo, "get_submission", lambda db, sid: sub)
    creator = client.get(f"/submissions/{sub.id}/detail", headers=employee_token(id=1)).json()
    assert creator["scores"]["total"] == 62.5
    # the respondent before results are revealed: no score, no breakdown
    own = client.get(f"/submissions/{sub.id}/detail", headers=employee_token(id=2)).json()
    assert own["score"] is None and own["scores"] is None


# ── the results query ────────────────────────────────────────────────────────

@pytest.fixture
def captured(monkeypatch):
    calls = []

    def aggregate(db, **kw):
        calls.append(kw)
        return [{"question_key": "k101", "count": 3, "avg_number": 4.5}], False

    monkeypatch.setattr(results_repo, "aggregate", aggregate)
    return calls


def query(client, headers, body=None):
    return client.post("/results/query", headers=headers, json=body if body is not None else {"form_id": 7})


ADMIN = employee_token(id=9, is_admin=True)
CREATOR = employee_token(id=1)
REVIEWER = employee_token(id=5, permissions=["submissions:read"], unit_id=31, assigned_unit_ids=[31, 32])


def test_admins_see_the_whole_organisation(client, exam, captured):
    res = query(client, ADMIN)
    assert res.status_code == 200, res.text
    assert res.json() == {"rows": [{"question_key": "k101", "count": 3, "avg_number": 4.5}],
                          "truncated": False, "scope": "organisation"}
    [call] = captured
    assert call["organisation_id"] == 10 and call["form_id"] == 7
    assert call["unit_ids"] is None
    assert call["group_by"] == ["question_key"] and call["measures"] == ["count", "submissions"]


def test_a_form_creator_sees_all_of_their_form(client, exam, captured):
    assert query(client, CREATOR).json()["scope"] == "organisation"
    assert captured[0]["unit_ids"] is None


def test_a_form_creator_without_review_rights_sees_nothing_across_forms(client, exam, captured):
    assert query(client, CREATOR, {"group_by": ["form_id"]}).status_code == 403


def test_reviewers_see_their_own_units(client, exam, captured):
    res = query(client, REVIEWER)
    assert res.json()["scope"] == "units"
    assert captured[0]["unit_ids"] == [31, 32]


def test_a_unit_filter_stays_inside_the_reviewers_units(client, exam, captured):
    query(client, REVIEWER, {"form_id": 7, "filters": {"unit_ids": [32, 99]}})
    assert captured[0]["unit_ids"] == [32]


def test_a_filter_outside_the_reviewers_units_returns_nothing_without_a_query(client, exam, captured):
    res = query(client, REVIEWER, {"form_id": 7, "filters": {"unit_ids": [99]}})
    assert res.json() == {"rows": [], "truncated": False, "scope": "units"}
    assert captured == []


def test_a_reviewer_without_a_unit_sees_nothing(client, exam, captured):
    headers = employee_token(id=5, permissions=["submissions:read"])
    assert query(client, headers).json()["rows"] == []
    assert captured == []


def test_admins_can_filter_by_any_unit(client, exam, captured):
    query(client, ADMIN, {"form_id": 7, "filters": {"unit_ids": [99]}})
    assert captured[0]["unit_ids"] == [99]


def test_employees_who_do_not_review_are_refused(client, exam, captured):
    agent = employee_token(id=6, permissions=["forms:read", "customers:read"], unit_id=31)
    assert query(client, agent).status_code == 403
    assert captured == []


def test_customers_are_refused(client, exam, captured):
    assert query(client, customer_token()).status_code in (401, 403)
    assert captured == []


def test_another_organisations_form_is_not_found(client, exam, captured):
    other_admin = employee_token(id=9, organisation_id=11, is_admin=True)
    assert query(client, other_admin).status_code == 404
    assert query(client, ADMIN, {"form_id": 12345}).status_code == 404
    assert captured == []


def test_filters_are_passed_through(client, exam, captured):
    body = {
        "form_id": 7,
        "filters": {
            "form_version_ids": [701], "question_keys": ["k101"], "subject_employee_ids": [3],
            "submitted_from": "2026-01-01T00:00:00Z", "submitted_to": "2026-02-01T00:00:00Z",
        },
        "group_by": ["unit_id", "month"],
        "measures": ["avg_number", "score_percent"],
        "limit": 10,
    }
    assert query(client, ADMIN, body).status_code == 200
    call = captured[0]
    assert call["form_version_ids"] == [701] and call["question_keys"] == ["k101"]
    assert call["subject_employee_ids"] == [3]
    assert call["submitted_from"] == datetime(2026, 1, 1, tzinfo=timezone.utc)
    assert call["submitted_to"] == datetime(2026, 2, 1, tzinfo=timezone.utc)
    assert call["group_by"] == ["unit_id", "month"] and call["limit"] == 10


@pytest.mark.parametrize("body", [
    {"group_by": ["unit_id", "unit_id"]},
    {"group_by": ["day", "month"]},
    {"group_by": ["respondent"]},
    {"measures": []},
    {"measures": ["count", "count"]},
    {"measures": ["median"]},
    {"limit": 0},
    {"limit": 5001},
    {"group_by": ["a", "b", "c", "d", "e"]},
    {"filters": {"question_keys": ["x" * 33]}},
    {"filters": {"submitted_from": "2026-02-01T00:00:00Z", "submitted_to": "2026-01-01T00:00:00Z"}},
])
def test_bad_queries_are_rejected(client, exam, captured, body):
    assert query(client, ADMIN, {"form_id": 7, **body}).status_code == 422
    assert captured == []


def test_response_values_are_plain_json(client, exam, monkeypatch):
    from decimal import Decimal

    monkeypatch.setattr(results_repo, "aggregate", lambda db, **kw: ([{
        "period": datetime(2026, 3, 1, tzinfo=timezone.utc), "value": "Good",
        "avg_number": Decimal("4.5"), "count": 2,
    }], True))
    body = query(client, ADMIN, {"form_id": 7, "group_by": ["month", "value"]}).json()
    assert body["rows"] == [{"period": "2026-03-01T00:00:00+00:00", "value": "Good", "avg_number": 4.5, "count": 2}]
    assert body["truncated"] is True


# ── the SQL ──────────────────────────────────────────────────────────────────

class Captures:
    def __init__(self, rows=()):
        self.statements = []
        self.rows = list(rows)

    def execute(self, stmt):
        self.statements.append(stmt)
        rows = self.rows
        return SimpleNamespace(mappings=lambda: SimpleNamespace(all=lambda: rows))


def sql(stmt) -> str:
    return str(stmt.compile(dialect=postgresql.dialect(), compile_kwargs={"literal_binds": True}))


def test_the_query_is_always_scoped_to_the_organisation():
    db = Captures()
    results_repo.aggregate(db, organisation_id=10, group_by=["question_key"], measures=["count"])
    text = sql(db.statements[0])
    assert "submission_values.organisation_id = 10" in text
    assert "GROUP BY submission_values.question_key" in text
    assert "LIMIT 1001" in text


def test_grouping_by_value_spreads_multiple_choice_options():
    db = Captures()
    results_repo.aggregate(db, organisation_id=10, group_by=["value"], measures=["count", "submissions"],
                           form_id=7, unit_ids=[31])
    text = sql(db.statements[0])
    assert "LEFT OUTER JOIN LATERAL jsonb_array_elements_text" in text
    assert "count(DISTINCT submission_values.submission_id)" in text
    assert "submission_values.unit_id IN (31)" in text


def test_time_buckets_use_one_inline_unit():
    db = Captures()
    results_repo.aggregate(db, organisation_id=10, group_by=["week"], measures=["avg_score", "score_percent"])
    text = sql(db.statements[0])
    # inline, so the select and the GROUP BY match exactly
    assert text.count("date_trunc('week', submission_values.submitted_at)") == 2  # select, group
    assert "ORDER BY period ASC NULLS LAST" in text
    assert "nullif(sum(submission_values.max_score), 0)" in text


def test_more_rows_than_the_limit_are_cut_and_flagged():
    db = Captures(rows=[{"count": i} for i in range(4)])
    rows, truncated = results_repo.aggregate(db, organisation_id=10, group_by=[], measures=["count"], limit=3)
    assert len(rows) == 3 and truncated
