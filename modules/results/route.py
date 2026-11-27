from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from db import get_db
from modules.auth.dto import EmployeePrincipal
from modules.auth.route import current_employee

from . import controller
from .dto import ResultsQuery, ResultsResponse, SummaryQuery, SummaryResponse

router = APIRouter(prefix="/results", tags=["results"])


# POST, not GET: the query is a JSON document (filters, groups, measures).
# It reads only.
@router.post("/query", response_model=ResultsResponse)
def query_results(
    payload: ResultsQuery,
    db: Session = Depends(get_db),
    employee: EmployeePrincipal = Depends(current_employee),
):
    return controller.query_results(db, payload, employee)


# Every question of a form, summarised the way its type is read: counts per
# option, averages, NPS groups, grid counts. Reads only.
@router.post("/summary", response_model=SummaryResponse)
def summarize_form(
    payload: SummaryQuery,
    db: Session = Depends(get_db),
    employee: EmployeePrincipal = Depends(current_employee),
):
    return controller.summary(db, payload, employee)
