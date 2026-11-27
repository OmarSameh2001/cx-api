from fastapi import Depends

from common.errors import AppError
from modules.auth.dto import EmployeePrincipal
from modules.auth.route import current_employee


def platform_admin(
    employee: EmployeePrincipal = Depends(current_employee),
) -> EmployeePrincipal:
    """Dependency for platform administration: organisations, tenants and the
    permission catalogue. Checks Employee.is_platform_admin (carried in the
    token), never a role permission.

    Usage:
        @router.post("/organisations")
        def create_organisation(..., employee=Depends(platform_admin)): ...
    """
    if not employee.is_platform_admin:
        raise AppError(403, "auth.platform_admin_required")
    return employee
