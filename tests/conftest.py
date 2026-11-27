"""Test harness that never touches a real database.

Requests go through the real app (middleware, auth, routing, error handlers)
with real signed tokens. `get_db` yields a FakeSession that records writes,
and each test stubs the repository functions it relies on. TestClient is
used without a `with` block, so the app's startup DB ping never runs.
"""

import os

# tests never touch the real Redis; counts stay in this process
os.environ["RATE_LIMIT_BACKEND"] = "memory"

import uuid
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

import main
from common.rate_limit import limiter
from db import get_db
from modules.auth.service import _encode_access_token
from modules.forms.model import Form, FormField, FormVersion
from modules.submissions.model import Submission


class FakeSession:
    def __init__(self):
        self.added = []
        self.deleted = []
        self.commits = 0
        self.rollbacks = 0
        self._next_id = 1000

    def _assign_id(self, obj):
        if getattr(obj, "id", None) is None:
            obj.id = self._next_id
            self._next_id += 1

    def add(self, obj):
        self.added.append(obj)

    def flush(self):
        for obj in self.added:
            self._assign_id(obj)

    def commit(self):
        self.flush()
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def begin_nested(self):
        # a savepoint: nothing to undo in memory, so just run the block
        from contextlib import nullcontext

        return nullcontext()

    def refresh(self, obj):
        self._assign_id(obj)
        # rows added to a relationship get their ids at flush, like children
        for child in getattr(obj, "fields", None) or []:
            self._assign_id(child)

    def delete(self, obj):
        self.deleted.append(obj)

    def close(self):
        pass

    def execute(self, *_args, **_kwargs):
        raise AssertionError("unexpected query: stub the repository function instead")


@pytest.fixture
def db():
    return FakeSession()


@pytest.fixture
def client(db):
    main.app.dependency_overrides[get_db] = lambda: db
    yield TestClient(main.app)
    main.app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _no_embedding_model(monkeypatch):
    # real text grading loads (and first downloads) an embedding model
    import modules.submissions.service as submissions_service

    monkeypatch.setattr(submissions_service, "score_text", lambda answer, reference: 0.5)


@pytest.fixture(autouse=True)
def _fresh_rate_limits():
    limiter.reset()
    yield
    limiter.reset()


def employee_token(
    id=1,
    organisation_id=10,
    permissions=(),
    is_admin=False,
    is_platform_admin=False,
    assigned_unit_ids=(),
    unit_id=None,
) -> dict[str, str]:
    token = _encode_access_token(
        {
            "principal": "employee",
            "id": id,
            "sub": f"employee:{id}",
            "jti": uuid.uuid4().hex,
            "organisation_id": organisation_id,
            "is_admin": is_admin,
            "is_platform_admin": is_platform_admin,
            "permissions": list(permissions),
            "unit_id": unit_id,
            "assigned_unit_ids": list(assigned_unit_ids),
        }
    )
    return {"Authorization": f"Bearer {token}"}


def customer_token(id=50) -> dict[str, str]:
    token = _encode_access_token(
        {"principal": "customer", "id": id, "sub": f"customer:{id}", "jti": uuid.uuid4().hex}
    )
    return {"Authorization": f"Bearer {token}"}


def make_form(published: bool = True, **overrides) -> Form:
    """An exam in org 10 created by employee 1, with sections, graded
    questions and a correct answer on each, published as version 1 (as an
    active form always is)."""
    data = dict(
        id=7,
        name="Safety exam",
        description="Read carefully",
        type="exam",
        is_active=True,
        is_archived=False,
        submitter_type=["employee", "customer"],
        assigned_to_units=None,
        time_limit_minutes=30,
        max_attempts=1,
        results_revealed=False,
        created_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        created_by=1,
        organisation_id=10,
        public_token="tok",
        sections=[
            {"id": 1, "title": "Basics", "description": None, "order": 0, "score_weight": 1.0},
            {"id": 2, "title": "More", "description": None, "order": 1, "score_weight": 3.0},
        ],
    )
    data.update(overrides)
    form = Form(**data)
    form.fields = [
        FormField(
            id=101, key="k101", question="Pick A", type="single_choice", options=["A", "B"],
            right_answer="A", order=0, help_text=None, is_required=True,
            score_weight=1.0, section_id=1, branching=None,
        ),
        FormField(
            id=102, key="k102", question="Explain", type="text", options=None,
            right_answer="Because of physics", order=1, help_text=None,
            is_required=False, score_weight=1.0, section_id=2, branching=None,
        ),
    ]
    if published:
        republish(form)
    return form


def republish(form: Form) -> FormVersion:
    """Publishes the form's draft as its next version, as /publish would."""
    from modules.forms.service import snapshot_of

    number = form.current_version.number + 1 if form.current_version is not None else 1
    version = FormVersion(
        id=form.id * 100 + number, form_id=form.id, number=number, snapshot=snapshot_of(form),
        published_at=datetime(2026, 1, 1, tzinfo=timezone.utc), published_by=form.created_by,
    )
    form.current_version = version
    form.current_version_id = version.id
    return version


def make_submission(form: Form, **overrides) -> Submission:
    data = dict(
        id=500, form_id=form.id, status="in_progress", answers={}, user_id=2,
        customer_id=None, attempt_number=1, results_revealed=False, score=None,
        started_at=datetime(2026, 1, 1, tzinfo=timezone.utc), expires_at=None,
        submitted_at=None,
    )
    data.update(overrides)
    submission = Submission(**data)
    submission.form = form
    if "form_version" not in overrides:
        submission.form_version = form.current_version
        submission.form_version_id = form.current_version_id
    return submission
