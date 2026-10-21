from fastapi import APIRouter, Depends

from modules.ai.errors import AI_ERROR_RESPONSES
from modules.auth.dto import EmployeePrincipal
from modules.auth.route import current_employee
from modules.forms.dto import FormCreate

from . import controller
from .dto import FormGenerateRequest


router = APIRouter(prefix="/forms")


@router.post("/generate", response_model=FormCreate, responses=AI_ERROR_RESPONSES)
async def generate_form(
    payload: FormGenerateRequest,
    employee: EmployeePrincipal = Depends(current_employee),
):
    """A complete form draft from a description, in the exact shape
    POST /forms accepts. Nothing is saved."""
    return await controller.generate_form(payload=payload, employee=employee)
