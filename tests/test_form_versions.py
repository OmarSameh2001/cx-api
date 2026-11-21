"""E1.5: form versions. The form row is the draft; respondents, scoring and
submission views use the published version a submission started on."""

from datetime import datetime, timezone

import pytest

from modules.events.model import OutboxEvent
from modules.forms import repository as forms_repo
from modules.forms import service as forms_service
from modules.forms.model import Form, FormField, FormVersion, PublishedForm
from modules.submissions import repository as subs_repo
from tests.conftest import employee_token, make_form, make_submission, republish

CREATOR = employee_token(id=1)
VIEWER = employee_token(id=9, permissions=["forms:read"])


@pytest.fixture
def versions(monkeypatch):
    """In-memory form_versions for the repository's version functions."""
    rows: list[FormVersion] = []

    def add_version(db, form, *, snapshot, published_by):
        number = max((v.number for v in rows if v.form_id == form.id), default=0) + 1
        version = FormVersion(
            id=5000 + len(rows), form_id=form.id, number=number, snapshot=snapshot,
            published_by=published_by, published_at=datetime(2026, 2, 1, tzinfo=timezone.utc),
        )
        rows.append(version)
        form.current_version = version
        form.current_version_id = version.id
        return version

    def for_form(form_id):
        return sorted((v for v in rows if v.form_id == form_id), key=lambda v: -v.number)

    monkeypatch.setattr(forms_repo, "add_version", add_version)
    monkeypatch.setattr(forms_repo, "list_versions", lambda db, form_id: for_form(form_id))
    monkeypatch.setattr(
        forms_repo, "get_version",
        lambda db, form_id, number: next((v for v in for_form(form_id) if v.number == number), None),
    )
    monkeypatch.setattr(forms_repo, "count_submissions_by_version", lambda db, form_id: {})
    return rows


@pytest.fixture
def live(monkeypatch, versions):
    """An active questionnaire published as version 1 (in `versions`)."""
    form = make_form(type="questionnaire", published=False, max_attempts=None)
    forms_service._publish(_NoDb(), form, 1)
    monkeypatch.setattr(forms_repo, "get_form", lambda db, fid: form if fid == form.id else None)
    monkeypatch.setattr(forms_repo, "get_form_by_token", lambda db, t: form if t == "tok" else None)
    monkeypatch.setattr(forms_repo, "form_has_submissions", lambda db, fid: False)
    return form


class _NoDb:
    def add(self, obj):
        pass


def edit(client, form, changes=None):
    """PATCH the draft with every field resent, `changes` keyed by field id."""
    fields = []
    for f in form.fields:
        row = {
            "id": f.id, "question": f.question, "type": f.type, "options": f.options,
            "right_answer": f.right_answer, "order": f.order, "help_text": f.help_text,
            "is_required": f.is_required, "score_weight": f.score_weight,
            "section_id": f.section_id, "branching": f.branching,
        }
        row.update((changes or {}).get(f.id, {}))
        fields.append(row)
    return client.patch(f"/forms/{form.id}", headers=CREATOR, json={"fields": fields, "sections": form.sections})


# ── creating and publishing ──────────────────────────────────────────────────

def test_creating_a_form_publishes_version_one(client, db, monkeypatch, versions):
    def create_form(db, *, data, fields, created_by, before_commit=None):
        form = Form(**data, created_by=created_by)
        form.id, form.is_active, form.is_archived = 70, True, False
        form.created_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
        form.fields = [FormField(id=900 + i, key=f"k{i}", **{k: v for k, v in f.items() if k != "id"})
                       for i, f in enumerate(fields)]
        before_commit(form)
        return form

    monkeypatch.setattr(forms_repo, "create_form", create_form)
    monkeypatch.setattr(forms_repo, "form_has_submissions", lambda db, fid: False)
    res = client.post("/forms", headers=employee_token(id=1, permissions=["forms:create"]), json={
        "name": "Survey", "submitter_type": ["customer"],
        "fields": [{"question": "How was it?", "type": "text"}],
    })
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["current_version"]["number"] == 1
    assert body["has_unpublished_changes"] is False
    assert body["fields"][0]["key"] == "k0"
    assert versions[0].snapshot["fields"][0]["question"] == "How was it?"
    events = [o for o in db.added if isinstance(o, OutboxEvent)]
    assert [(e.event_type, e.payload["version"]) for e in events] == [("form.published", 1)]


def test_editing_the_draft_does_not_change_the_published_form(client, live):
    res = edit(client, live, {101: {"question": "Pick A (reworded)"}})
    assert res.status_code == 200, res.text
    assert res.json()["has_unpublished_changes"] is True
    assert res.json()["current_version"]["number"] == 1
    public = client.get("/public/forms/tok").json()
    assert public["fields"][0]["question"] == "Pick A"


def test_publish_makes_the_draft_live(client, db, live):
    edit(client, live, {101: {"question": "Pick A (reworded)"}})
    res = client.post(f"/forms/{live.id}/publish", headers=CREATOR)
    assert res.status_code == 200, res.text
    assert res.json()["current_version"]["number"] == 2
    assert res.json()["has_unpublished_changes"] is False
    assert client.get("/public/forms/tok").json()["fields"][0]["question"] == "Pick A (reworded)"
    assert any(isinstance(o, OutboxEvent) and o.payload["version"] == 2 for o in db.added)


def test_publish_with_nothing_new_is_refused(client, live):
    res = client.post(f"/forms/{live.id}/publish", headers=CREATOR)
    assert res.status_code == 409 and res.json()["error"] == "nothing_to_publish"


def test_publish_needs_manage_rights(client, live):
    edit(client, live, {101: {"question": "changed"}})
    assert client.post(f"/forms/{live.id}/publish", headers=VIEWER).status_code == 403


def test_activating_publishes_pending_changes_only(client, live, versions):
    # the builder's flow: deactivate, edit, activate
    client.post(f"/forms/{live.id}/deactivate", headers=CREATOR)
    client.post(f"/forms/{live.id}/activate", headers=CREATOR)
    assert len(versions) == 1  # nothing changed, nothing published
    client.post(f"/forms/{live.id}/deactivate", headers=CREATOR)
    edit(client, live, {101: {"question": "changed"}})
    res = client.post(f"/forms/{live.id}/activate", headers=CREATOR)
    assert res.status_code == 200
    assert res.json()["current_version"]["number"] == 2 and len(versions) == 2


def test_only_section_defaults_differing_is_not_a_change(live):
    # sections stored before a key existed compare equal to the same sections saved again
    live.sections = [{**s, "next_section_id": None} for s in live.sections]
    assert forms_service.has_unpublished_changes(live) is False


def test_a_never_published_form_has_changes_and_takes_no_responses(client, monkeypatch):
    form = make_form(type="questionnaire", published=False)
    monkeypatch.setattr(forms_repo, "get_form", lambda db, fid: form)
    monkeypatch.setattr(forms_repo, "get_form_by_token", lambda db, t: form)
    assert forms_service.has_unpublished_changes(form) is True
    assert client.get("/public/forms/tok").status_code == 409
    res = client.post("/submissions/start", headers=employee_token(id=2), json={"form_id": form.id})
    assert res.status_code == 409


# ── submissions stay on their version ───────────────────────────────────────

@pytest.fixture
def started(monkeypatch, live):
    """Captures create_submission and returns the created submission."""
    holder = {}

    def create_submission(db, **kw):
        sub = make_submission(live, form_version=None)
        sub.form_version_id = kw["form_version_id"]
        sub.form_version = next(v for v in [live.current_version] if v.id == kw["form_version_id"])
        holder["sub"] = sub
        return sub

    monkeypatch.setattr(subs_repo, "find_open_submission", lambda db, **kw: None)
    monkeypatch.setattr(subs_repo, "count_finalized_attempts", lambda db, **kw: 0)
    monkeypatch.setattr(subs_repo, "create_submission", create_submission)
    monkeypatch.setattr(subs_repo, "get_submission", lambda db, sid: holder.get("sub"))
    monkeypatch.setattr(subs_repo, "save", lambda db, s: s)
    return holder


def test_a_submission_records_the_version_it_started_on(client, live, started):
    res = client.post("/submissions/start", headers=employee_token(id=2), json={"form_id": live.id})
    assert res.status_code == 201, res.text
    assert res.json()["form_version_id"] == live.current_version_id


def test_an_attempt_started_before_a_publish_is_scored_on_its_version(client, live, started):
    client.post("/submissions/start", headers=employee_token(id=2), json={"form_id": live.id})
    sub = started["sub"]
    # version 2 changes the correct answer and removes the text question
    live.fields[0].right_answer = "B"
    live.fields.pop()
    republish(live)
    assert client.get(f"/submissions/{sub.id}/form", headers=employee_token(id=2)).json()["fields"][1]["id"] == 102
    res = client.post(f"/submissions/{sub.id}/submit", headers=employee_token(id=2),
                      json={"answers": {"101": "A", "102": "Because of physics"}})
    assert res.status_code == 200, res.text
    assert sub.answers["101"] == "A" and "102" in sub.answers  # kept: on its version
    # graded against version 1, where A was right: sections weigh 1 and 3,
    # text scores 0.5 in tests, so 25 + 37.5 (version 2 would give 0)
    assert sub.score == pytest.approx(62.5)
    reviewer = client.get(f"/submissions/{sub.id}/detail", headers=CREATOR).json()
    assert [f["id"] for f in reviewer["fields"]] == [101, 102]
    assert reviewer["fields"][0]["right_answer"] == "A"


def test_a_new_attempt_gets_the_current_version(client, live, started):
    live.fields[0].question = "v2 question"
    republish(live)
    client.post("/submissions/start", headers=employee_token(id=2), json={"form_id": live.id})
    sub = started["sub"]
    form = client.get(f"/submissions/{sub.id}/form", headers=employee_token(id=2)).json()
    assert form["fields"][0]["question"] == "v2 question"


def test_public_submissions_record_the_current_version(client, db, live, monkeypatch):
    from modules.customers import repository as customers_repo
    from modules.submissions.model import Submission

    monkeypatch.setattr(customers_repo, "get_by_email", lambda db, **kw: None)
    monkeypatch.setattr(subs_repo, "count_finalized_attempts", lambda db, **kw: 0)
    res = client.post("/public/forms/tok/submit", json={
        "customer": {"email": "ann@acme.io", "first_name": "Ann", "last_name": "Lee"},
        "answers": {"101": "A"},
    })
    assert res.status_code == 201, res.text
    sub = next(o for o in db.added if isinstance(o, Submission))
    assert sub.form_version_id == live.current_version_id


def test_the_draft_never_reaches_respondents(client, live):
    edit(client, live, {101: {"question": "DRAFT ONLY"}})
    assert "DRAFT ONLY" not in client.get("/public/forms/tok").text


# ── keys ─────────────────────────────────────────────────────────────────────

def test_keys_survive_edits_and_change_with_the_type(client, live):
    res = edit(client, live, {101: {"question": "reworded"}, 102: {"type": "email", "right_answer": None}})
    assert res.status_code == 200, res.text
    by_id = {f["id"]: f for f in res.json()["fields"]}
    assert by_id[101]["key"] == "k101"
    assert by_id[102]["key"] not in (None, "k102")  # answers of another type aren't comparable


def test_new_questions_get_a_key(client, live):
    res = client.patch(f"/forms/{live.id}", headers=CREATOR, json={
        "fields": [{"question": "new", "type": "text"}],
    })
    assert res.status_code == 200, res.text
    key = res.json()["fields"][0]["key"]
    assert key and len(key) == 32


def test_a_published_form_keeps_its_type(client, live):
    res = client.patch(f"/forms/{live.id}", headers=CREATOR, json={"type": "exam"})
    assert res.status_code == 409 and res.json()["error"] == "form_type_locked"


def test_an_unpublished_form_can_change_type(client, monkeypatch):
    form = make_form(type="questionnaire", published=False, is_active=False)
    monkeypatch.setattr(forms_repo, "get_form", lambda db, fid: form)
    monkeypatch.setattr(forms_repo, "form_has_submissions", lambda db, fid: False)
    assert client.patch(f"/forms/{form.id}", headers=CREATOR, json={"type": "exam"}).status_code == 200


# ── version list, read, diff, restore ───────────────────────────────────────

def two_versions(client, live):
    edit(client, live, {101: {"question": "Pick A v2", "right_answer": "B"}})
    client.patch(f"/forms/{live.id}", headers=CREATOR, json={
        "fields": [
            {"id": 101, "question": "Pick A v2", "type": "single_choice", "options": ["A", "B"],
             "right_answer": "B", "score_weight": 1.0, "section_id": 1, "is_required": True},
            {"question": "Added in v2", "type": "text", "section_id": 2},
        ],
        "sections": [{**live.sections[0], "title": "Basics v2"}, live.sections[1]],
    })
    assert client.post(f"/forms/{live.id}/publish", headers=CREATOR).status_code == 200


def test_version_list(client, live):
    two_versions(client, live)
    res = client.get(f"/forms/{live.id}/versions", headers=VIEWER)
    assert res.status_code == 200, res.text
    assert [(v["number"], v["question_count"]) for v in res.json()] == [(2, 2), (1, 2)]


def test_version_read_hides_answers_from_viewers(client, live):
    two_versions(client, live)
    as_creator = client.get(f"/forms/{live.id}/versions/1", headers=CREATOR).json()
    assert as_creator["fields"][0]["right_answer"] == "A"
    as_viewer = client.get(f"/forms/{live.id}/versions/1", headers=VIEWER).json()
    assert [f["right_answer"] for f in as_viewer["fields"]] == [None, None]
    assert client.get(f"/forms/{live.id}/versions/9", headers=CREATOR).status_code == 404


def test_versions_are_scoped_to_the_organisation(client, live):
    other = employee_token(id=1, organisation_id=99, is_admin=True)
    assert client.get(f"/forms/{live.id}/versions", headers=other).status_code == 404
    assert client.get(f"/forms/{live.id}/versions/1", headers=other).status_code == 404


def test_diff_against_the_previous_version(client, live):
    two_versions(client, live)
    res = client.get(f"/forms/{live.id}/versions/2/diff", headers=CREATOR)
    assert res.status_code == 200, res.text
    d = res.json()
    assert (d["from_number"], d["to"]) == (1, 2)
    assert [i["label"] for i in d["questions"]["added"]] == ["Added in v2"]
    assert [i["ref"] for i in d["questions"]["removed"]] == ["k102"]
    changed = {i["ref"]: i["changes"] for i in d["questions"]["changed"]}
    assert set(changed["k101"]) == {"question", "right_answer"}
    assert d["sections"]["changed"] == [{"ref": 1, "label": "Basics v2", "changes": ["title"]}]


def test_diff_of_version_one_and_against_the_draft(client, live):
    first = client.get(f"/forms/{live.id}/versions/1/diff", headers=CREATOR).json()
    assert first["from_number"] is None and len(first["questions"]["added"]) == 2
    edit(client, live, {101: {"help_text": "new hint"}})
    draft = client.get(f"/forms/{live.id}/versions/1/diff?against=draft", headers=CREATOR).json()
    assert draft["to"] == "draft"
    assert draft["questions"]["changed"] == [{"ref": "k101", "label": "Pick A", "changes": ["help_text"]}]
    assert client.get(f"/forms/{live.id}/versions/1/diff?against=x", headers=CREATOR).status_code == 422


def test_restore_puts_a_version_back_in_the_draft(client, live):
    two_versions(client, live)
    res = client.post(f"/forms/{live.id}/versions/1/restore", headers=CREATOR)
    assert res.status_code == 200, res.text
    body = res.json()
    by_key = {f["key"]: f for f in body["fields"]}
    assert set(by_key) == {"k101", "k102"}
    assert by_key["k101"]["id"] == 101  # still in the draft: same row
    assert by_key["k101"]["right_answer"] == "A" and by_key["k101"]["question"] == "Pick A"
    assert by_key["k102"]["id"] != 102  # came back as a new row with its old key
    assert body["sections"][0]["title"] == "Basics"
    # nothing reaches respondents until it's published
    assert body["current_version"]["number"] == 2 and body["has_unpublished_changes"] is True
    assert client.post(f"/forms/{live.id}/publish", headers=CREATOR).json()["current_version"]["number"] == 3


def test_only_the_creator_restores(client, live):
    two_versions(client, live)
    other = employee_token(id=5, is_admin=True)
    assert client.post(f"/forms/{live.id}/versions/1/restore", headers=other).status_code == 403


# ── the published view ───────────────────────────────────────────────────────

def test_published_view_reads_structure_from_the_version_and_the_rest_live(live):
    live.fields[0].question = "draft"
    live.name = "Renamed"
    view = PublishedForm(live, live.current_version)
    assert view.fields[0].question == "Pick A"
    assert (view.name, view.id, view.organisation_id) == ("Renamed", live.id, live.organisation_id)


def test_file_questions_are_found_in_published_versions_first(live, versions):
    v1_field = forms_service.find_published_field(None, live, 102)
    assert v1_field.question == "Explain"
    live.fields.pop()  # 102 leaves the draft, and version 2
    republish(live)
    versions.insert(0, live.current_version)
    # an attempt on version 1 can still upload to it
    assert forms_service.find_published_field(None, live, 102).question == "Explain"
    live.fields.append(FormField(id=103, key="k103", question="only in draft", type="file",
                                 order=5, is_required=False, score_weight=0.0))
    assert forms_service.find_published_field(None, live, 103).question == "only in draft"
    assert forms_service.find_published_field(None, live, 999) is None
