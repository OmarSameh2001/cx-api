"""Blocker 3 and E0.4: public submissions. Nothing is written for a rejected
submission, the response says nothing about the customer record, customers
are matched only inside the form's organisation and never overwritten, and
requests are rate and size limited."""

from types import SimpleNamespace

import pytest

from modules.customers import repository as customers_repo
from modules.customers.model import Customer
from modules.forms import repository as forms_repo
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
    """Set .customer to make an email known; .lookups records each search."""
    holder = SimpleNamespace(customer=None, lookups=[])

    def get_by_email(db, *, organisation_id, email):
        holder.lookups.append((organisation_id, email))
        c = holder.customer
        return c if c is not None and c.organisation_id == organisation_id else None

    monkeypatch.setattr(customers_repo, "get_by_email", get_by_email)
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


def test_customer_is_looked_up_only_in_the_forms_organisation(client, db, public_form, known_customer):
    # the same email is a customer of another organisation: not a match here
    known_customer.customer = Customer(id=5, organisation_id=99, email="ann@acme.io",
                                       first_name="Ann", last_name="Lee")
    res = submit(client, {"101": "A"}, details={**DETAILS, "email": "Ann@Acme.io"})
    assert res.status_code == 201
    ((org_id, email),) = known_customer.lookups
    assert org_id == public_form.organisation_id and email.lower() == "ann@acme.io"

    (created,) = [o for o in db.added if isinstance(o, Customer)]
    assert created.organisation_id == public_form.organisation_id
    assert created.email == "ann@acme.io"  # stored lowercased
    submission = next(o for o in db.added if isinstance(o, Submission))
    assert submission.customer_id == created.id


def test_returning_customer_with_new_details_is_accepted_and_not_overwritten(
    client, db, public_form, known_customer
):
    stored = Customer(id=5, organisation_id=public_form.organisation_id, email="ann@acme.io",
                      first_name="Ann", last_name="Lee", phone=None)
    known_customer.customer = stored
    res = submit(client, {"101": "A"},
                 details={**DETAILS, "first_name": " Annie ", "phone": "+1 555 0100"})
    assert res.status_code == 201

    # the record keeps its first-contact details, phone included
    assert (stored.first_name, stored.last_name, stored.phone) == ("Ann", "Lee", None)
    assert written(db) == (["Submission"], 1)  # no new customer
    submission = db.added[0]
    assert submission.customer_id == 5
    assert submission.contact == {
        "email": "ann@acme.io", "first_name": "Annie", "last_name": "Lee", "phone": "+1 555 0100",
    }


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


# ── E0.4: customer login is gone ─────────────────────────────────────────────

def test_customer_login_endpoint_is_gone(client):
    res = client.post("/auth/customer/login", json={"email": "c@acme.com", "password": "x"})
    # no longer a public path, and no such route behind the auth middleware
    assert res.status_code in (401, 404)


def test_customer_lookup_is_scoped_to_the_callers_organisation(client, monkeypatch):
    from tests.conftest import employee_token

    seen = {}

    def search(db, *, organisation_id, search, limit):
        seen["org"] = organisation_id
        return [Customer(id=1, organisation_id=organisation_id, email="ann@acme.io",
                         first_name="Ann", last_name="Lee")]

    monkeypatch.setattr(customers_repo, "search", search)
    res = client.get("/lookups/customers", headers=employee_token(organisation_id=10))
    assert res.status_code == 200
    assert seen == {"org": 10}
    assert res.json() == [{"id": 1, "name": "Ann Lee", "email": "ann"}]


# ── E0.4: contact details on the submission ──────────────────────────────────

def test_contact_details_are_shown_to_reviewers_only(client, monkeypatch):
    from tests.conftest import employee_token, make_submission

    form = make_form(type="questionnaire")
    contact = {"email": "ann@acme.io", "first_name": "Annie", "last_name": "Lee", "phone": None}
    sub = make_submission(form, status="submitted", user_id=None, customer_id=5, contact=contact)
    sub.employee = None
    sub.customer = Customer(id=5, organisation_id=10, email="ann@acme.io",
                            first_name="Ann", last_name="Lee")
    monkeypatch.setattr(subs_repo, "get_submission", lambda db, sid: sub)

    reviewer = client.get("/submissions/500/detail",
                          headers=employee_token(id=9, permissions=["submissions:read"]))
    assert reviewer.status_code == 200
    assert reviewer.json()["contact"] == contact
    # the name given with this submission, not the stored record's
    assert reviewer.json()["submitter_name"] == "Annie Lee"

    listing = client.get("/submissions/500", headers=employee_token(id=9, permissions=["submissions:read"]))
    assert listing.json()["submitter_name"] == "Annie Lee"
