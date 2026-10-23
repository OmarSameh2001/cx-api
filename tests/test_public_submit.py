"""Blocker 3: public submissions. Nothing is written for a rejected
submission, the response says nothing about the customer record, mismatches
don't say what was wrong, and requests are rate and size limited."""

from types import SimpleNamespace

import pytest

from modules.customers.model import Customer
from modules.forms import repository as forms_repo
from modules.public_api import service as public_service
from modules.submissions import repository as subs_repo
from modules.submissions.model import Submission
from tests.conftest import make_form

URL = "/public/forms/tok/submit"
DETAILS = {"email": "ann@acme.io", "first_name": "Ann", "last_name": "Lee"}


@pytest.fixture
def public_form(monkeypatch):
    form = make_form(type="questionnaire", max_attempts=2)
    monkeypatch.setattr(forms_repo, "get_form_by_token", lambda db, t: form if t == "tok" else None)
    monkeypatch.setattr(subs_repo, "count_finalized_attempts", lambda db, **kw: 0)
    return form


@pytest.fixture
def known_customer(monkeypatch):
    holder = SimpleNamespace(customer=None)
    monkeypatch.setattr(public_service, "_find_customer_by_email", lambda db, e: holder.customer)
    return holder


def submit(client, answers, details=DETAILS, ip="203.0.113.5"):
    return client.post(
        URL,
        json={"customer": details, "answers": answers},
        headers={"X-Forwarded-For": ip},
    )


def written(db):
    return [type(o).__name__ for o in db.added], db.commits


def test_valid_submission_commits_customer_and_submission_once(client, db, public_form, known_customer):
    res = submit(client, {"101": "A", "102": "it's physics"})
    assert res.status_code == 201
    assert res.json() == {"submission_id": res.json()["submission_id"]}  # nothing else
    assert written(db) == (["Customer", "Submission"], 1)


@pytest.mark.parametrize(
    "answers, why",
    [
        ({"101": "Z"}, "not an option"),
        ({"101": ["A"]}, "wrong shape"),
        ({"101": "A", "102": "x" * 5001}, "text too long"),
        ({"102": "only the optional one"}, "required missing"),
    ],
)
def test_rejected_answers_leave_nothing_behind(client, db, public_form, known_customer, answers, why):
    res = submit(client, answers)
    assert res.status_code == 422, why
    assert written(db) == ([], 0)


def test_unknown_answer_keys_are_dropped(client, db, public_form, known_customer):
    res = submit(client, {"101": "A", "999": "junk", "__proto__": "x"})
    assert res.status_code == 201
    submission = next(o for o in db.added if isinstance(o, Submission))
    assert submission.answers == {"101": "A"}


def test_details_mismatch_is_generic_and_writes_nothing(client, db, public_form, known_customer):
    known_customer.customer = Customer(
        id=5, email="ann@acme.io", first_name="Ann", last_name="Lee", phone="+1 555 0100"
    )
    messages = set()
    for wrong in ({"first_name": "Bob"}, {"last_name": "Kim"}, {"phone": "999"}):
        res = submit(client, {"101": "A"}, details={**DETAILS, **wrong})
        assert res.status_code == 409
        assert res.json()["error"] == "customer_details_mismatch"
        messages.add(res.json()["detail"])
    assert len(messages) == 1  # can't tell which detail was wrong
    assert db.commits == 0


def test_attempt_limit_rolls_back_the_new_customer(client, db, monkeypatch, public_form, known_customer):
    monkeypatch.setattr(subs_repo, "count_finalized_attempts", lambda db, **kw: 2)
    res = submit(client, {"101": "A"})
    assert res.status_code == 409
    assert db.commits == 0 and db.rollbacks == 1


def test_submits_are_rate_limited_per_ip(client, public_form, known_customer):
    codes = [submit(client, {"101": "Z"}, details={**DETAILS, "email": f"u{i}@acme.io"}).status_code
             for i in range(11)]
    assert codes[:10] == [422] * 10
    assert codes[10] == 429


def test_submits_are_rate_limited_per_email_across_ips(client, public_form, known_customer):
    codes = [submit(client, {"101": "Z"}, ip=f"198.51.100.{i}").status_code for i in range(6)]
    assert codes[:5] == [422] * 5
    res = submit(client, {"101": "Z"}, ip="198.51.100.77")
    assert res.status_code == 429
    assert res.json()["error"] == "rate_limited"
    assert int(res.headers["Retry-After"]) > 0


def test_oversized_body_is_rejected_before_the_route(client, db, public_form, known_customer):
    res = submit(client, {"101": "A", "102": "x" * (300 * 1024)})
    assert res.status_code == 413
    assert res.json()["error"] == "payload_too_large"
    assert written(db) == ([], 0)
