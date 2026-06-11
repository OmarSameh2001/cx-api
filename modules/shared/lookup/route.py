from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from db import get_db
from modules.auth.dto import EmployeePrincipal
from modules.auth.route import current_employee

from .customer_lookup import CustomerLookup, search_customers
from .employee_lookup import EmployeeLookup, search_employees
from .form_lookup import FormLookup, search_forms
from .role_lookup import RoleLookup, search_roles
from .unit_lookup import UnitLookup, search_units


router = APIRouter(prefix="/lookups", tags=["lookups"])


@router.get("/employees", response_model=list[EmployeeLookup])
def employees_lookup(
    search: Optional[str] = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    emp: EmployeePrincipal = Depends(current_employee),
):
    return search_employees(db, parent_unit_ids=emp.assigned_unit_ids, search=search, limit=limit)


@router.get("/customers", response_model=list[CustomerLookup])
def customers_lookup(
    search: Optional[str] = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    _: EmployeePrincipal = Depends(current_employee),
):
    return search_customers(db, search=search, limit=limit)


@router.get("/units", response_model=list[UnitLookup])
def units_lookup(
    search: Optional[str] = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    emp: EmployeePrincipal = Depends(current_employee),
):
    return search_units(
        db,
        allowed_ids=None if emp.is_admin else emp.assigned_unit_ids,
        organisation_id=emp.organisation_id,
        search=search,
        limit=limit,
    )


@router.get("/forms", response_model=list[FormLookup])
def forms_lookup(
    search: Optional[str] = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    emp: EmployeePrincipal = Depends(current_employee),
):
    return search_forms(db, allowed_unit_ids=emp.assigned_unit_ids, search=search, limit=limit)


@router.get("/roles", response_model=list[RoleLookup])
def roles_lookup(
    search: Optional[str] = Query(default=None),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    _: EmployeePrincipal = Depends(current_employee),
):
    return search_roles(db, search=search, limit=limit)
