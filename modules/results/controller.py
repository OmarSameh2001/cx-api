from sqlalchemy.orm import Session

from modules.auth.dto import EmployeePrincipal

from . import service
from .dto import ResultsQuery, ResultsResponse


def query_results(db: Session, payload: ResultsQuery, employee: EmployeePrincipal) -> ResultsResponse:
    return service.query(db, employee=employee, payload=payload)
