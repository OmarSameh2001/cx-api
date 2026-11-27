from sqlalchemy.orm import Session

from modules.auth.dto import EmployeePrincipal

from . import service
from .dto import ResultsQuery, ResultsResponse, SummaryQuery, SummaryResponse


def query_results(db: Session, payload: ResultsQuery, employee: EmployeePrincipal) -> ResultsResponse:
    return service.query(db, employee=employee, payload=payload)


def summary(db: Session, payload: SummaryQuery, employee: EmployeePrincipal) -> SummaryResponse:
    return service.summary(db, employee=employee, payload=payload)
