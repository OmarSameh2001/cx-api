from modules.auth.dto import EmployeePrincipal
from modules.forms.dto import FormCreate

from . import service
from .dto import FormGenerateRequest


async def generate_form(*, payload: FormGenerateRequest, employee: EmployeePrincipal) -> FormCreate:
    # nothing is saved: the builder loads the draft and the user saves it
    return await service.generate_form(payload)
