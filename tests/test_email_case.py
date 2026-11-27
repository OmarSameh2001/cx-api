"""Signing in and adding employees treat an email's case as the same address."""

from types import SimpleNamespace

from modules.auth import repository as auth_repo
from modules.employees import repository as employees_repo


class _Result:
    def __init__(self, rows):
        self._rows = rows

    def scalar_one_or_none(self):
        return self._rows[0] if self._rows else None

    def scalars(self):
        return self

    def first(self):
        return self._rows[0] if self._rows else None

    def __iter__(self):
        return iter(self._rows)


class _DB:
    """Answers each query with the next canned result, and keeps the SQL."""

    def __init__(self, *results):
        self._results = list(results)
        self.sql = []

    def execute(self, stmt):
        self.sql.append(str(stmt.compile(compile_kwargs={"literal_binds": True})))
        return _Result(self._results.pop(0))


def test_sign_in_prefers_the_exact_email():
    ali = SimpleNamespace(id=1)
    db = _DB([ali])
    assert auth_repo.get_employee_by_email(db, "Ali@X.co") is ali
    assert len(db.sql) == 1


def test_sign_in_ignores_case_when_one_account_matches():
    ali = SimpleNamespace(id=1)
    db = _DB([], [ali])
    assert auth_repo.get_employee_by_email(db, " Ali@X.co ") is ali
    assert "lower(employees.email) = 'ali@x.co'" in db.sql[1]


def test_sign_in_refuses_an_email_that_matches_two_accounts_by_case():
    db = _DB([], [SimpleNamespace(id=1), SimpleNamespace(id=2)])
    assert auth_repo.get_employee_by_email(db, "ali@x.co") is None


def test_adding_an_employee_finds_the_same_email_in_another_case():
    ali = SimpleNamespace(id=1)
    db = _DB([ali])
    assert employees_repo.get_employee_by_email(db, "ALI@x.co") is ali
    assert "lower(employees.email) = 'ali@x.co'" in db.sql[0]
