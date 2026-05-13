import inspect
from functools import wraps
from typing import Callable, Literal

from fastapi import Depends, HTTPException, status

from modules.auth.dto import EmployeePrincipal
from modules.auth.route import current_employee


_GUARD_KW = "__permission_guard_principal__"

Mode = Literal["all", "any"]


def require_permission(*needed: str, mode: Mode = "all") -> Callable:
    """Route decorator that enforces permissions on the current employee.

    Usage:
        @router.get("/forms")
        @require_permission("forms:read")
        def list_forms(...): ...

        @require_permission("forms:create", "forms:admin", mode="any")
        def update_form(...): ...
    """
    if not needed:
        raise ValueError("require_permission needs at least one permission")

    def decorator(func: Callable) -> Callable:
        sig = inspect.signature(func)
        if _GUARD_KW in sig.parameters:
            raise ValueError(f"{_GUARD_KW} is reserved")

        guard_param = inspect.Parameter(
            _GUARD_KW,
            kind=inspect.Parameter.KEYWORD_ONLY,
            default=Depends(current_employee),
            annotation=EmployeePrincipal,
        )
        new_sig = sig.replace(parameters=[*sig.parameters.values(), guard_param])

        def _check(principal: EmployeePrincipal) -> None:
            owned = set(principal.permissions or [])
            if mode == "any":
                if not any(p in owned for p in needed):
                    raise HTTPException(
                        status.HTTP_403_FORBIDDEN,
                        f"Requires any of: {', '.join(needed)}",
                    )
                return
            missing = [p for p in needed if p not in owned]
            if missing:
                raise HTTPException(
                    status.HTTP_403_FORBIDDEN,
                    f"You dont have the required permissions: {', '.join(missing)}",
                )

        if inspect.iscoroutinefunction(func):
            @wraps(func)
            async def wrapper(*args, **kwargs):
                _check(kwargs.pop(_GUARD_KW))
                return await func(*args, **kwargs)
        else:
            @wraps(func)
            def wrapper(*args, **kwargs):
                _check(kwargs.pop(_GUARD_KW))
                return func(*args, **kwargs)

        wrapper.__signature__ = new_sig  # type: ignore[attr-defined]
        return wrapper

    return decorator
