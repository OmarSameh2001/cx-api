from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from db import get_db
from modules.auth.dto import EmployeePrincipal
from modules.auth.route import current_employee

from . import controller
from .dto import ResultsQuery, ResultsResponse

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
