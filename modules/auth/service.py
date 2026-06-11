from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import uuid4

import bcrypt
import jwt
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from config import AuthEnv
from modules.units.repository import get_descendant_unit_ids

from . import repository


class AuthError(HTTPException):
    def __init__(self, detail: str, code: int = status.HTTP_401_UNAUTHORIZED):
        super().__init__(status_code=code, detail=detail)


def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _encode_access_token(claims: dict[str, Any]) -> str:
    iat = _now()
    payload = {
        **claims,
        "iss": AuthEnv.JWT_ISSUER,
        "iat": int(iat.timestamp()),
        "exp": int((iat + timedelta(minutes=AuthEnv.ACCESS_TOKEN_EXPIRE_MINUTES)).timestamp()),
        "typ": "access",
    }
    return jwt.encode(payload, AuthEnv.JWT_SECRET, algorithm=AuthEnv.JWT_ALGORITHM)


def decode_access_token(token: str) -> dict[str, Any]:
    payload = jwt.decode(
        token,
        AuthEnv.JWT_SECRET,
        algorithms=[AuthEnv.JWT_ALGORITHM],
        issuer=AuthEnv.JWT_ISSUER,
    )
    if payload.get("typ") != "access":
        raise jwt.InvalidTokenError("Wrong token type")
    return payload


def _encode_refresh_token(
    principal_type: str,
    principal_id: int,
    user_agent: Optional[str],
    ip: Optional[str],
) -> tuple[str, str]:
    iat = _now()
    exp = iat + timedelta(days=AuthEnv.REFRESH_TOKEN_EXPIRE_DAYS)
    jti = uuid4().hex
    payload = {
        "iss": AuthEnv.JWT_ISSUER,
        "sub": f"{principal_type}:{principal_id}",
        "principal": principal_type,
        "id": principal_id,
        "jti": jti,
        "iat": int(iat.timestamp()),
        "exp": int(exp.timestamp()),
        "typ": "refresh",
        "user_agent": user_agent,
        "ip": ip,
    }
    token = jwt.encode(payload, AuthEnv.JWT_REFRESH_SECRET, algorithm=AuthEnv.JWT_ALGORITHM)
    return token, jti


def _decode_refresh_token(token: str) -> dict[str, Any]:
    payload = jwt.decode(
        token,
        AuthEnv.JWT_REFRESH_SECRET,
        algorithms=[AuthEnv.JWT_ALGORITHM],
        issuer=AuthEnv.JWT_ISSUER,
    )
    if payload.get("typ") != "refresh":
        raise jwt.InvalidTokenError("Wrong token type")
    return payload


def _build_employee_claims(db: Session, employee) -> dict:
    permissions: list[str] = []
    role_name: Optional[str] = None
    is_admin: bool = False
    if employee.role_id is not None:
        permissions = repository.list_permission_names_for_role(db, employee.role_id)
        role = repository.get_role_with_permissions(db, employee.role_id)
        role_name = role.name if role else None
        is_admin = role.is_system if role else False

    assigned_unit_ids: list[int] = []
    if employee.unit_id is not None:
        assigned_unit_ids = get_descendant_unit_ids(db, employee.unit_id)

    return {
        "principal": "employee",
        "id": employee.id,
        "sub": f"employee:{employee.id}",
        "organisation_id": employee.organisation_id,
        "role_id": employee.role_id,
        "role": role_name,
        "is_admin": is_admin,
        "permissions": permissions,
        "unit_id": employee.unit_id,
        "assigned_unit_ids": assigned_unit_ids,
    }


def _build_customer_claims(customer) -> dict:
    return {
        "principal": "customer",
        "id": customer.id,
        "sub": f"customer:{customer.id}",
    }


def _issue_tokens(
    db: Session,
    *,
    principal_type: str,
    principal_id: int,
    base_claims: dict,
    user_agent: Optional[str],
    ip: Optional[str],
) -> tuple[str, str, int]:
    refresh_token, jti = _encode_refresh_token(principal_type, principal_id, user_agent, ip)
    repository.add_refresh_jti(db, principal_type, principal_id, jti)
    access_token = _encode_access_token({**base_claims, "jti": jti})
    expires_in = AuthEnv.ACCESS_TOKEN_EXPIRE_MINUTES * 60
    return access_token, refresh_token, expires_in


def login_employee(
    db: Session, *, email: str, password: str, user_agent: Optional[str], ip: Optional[str]
):
    employee = repository.get_employee_by_email(db, email)
    if employee is None or not verify_password(password, employee.password):
        raise AuthError("Invalid email or password")
    if not employee.is_active:
        raise AuthError("Account is disabled", code=status.HTTP_403_FORBIDDEN)

    claims = _build_employee_claims(db, employee)
    access, refresh, expires_in = _issue_tokens(
        db,
        principal_type="employee",
        principal_id=employee.id,
        base_claims=claims,
        user_agent=user_agent,
        ip=ip,
    )
    return employee, claims, access, refresh, expires_in


def login_customer(
    db: Session, *, email: str, password: str, user_agent: Optional[str], ip: Optional[str]
):
    customer = repository.get_customer_by_email(db, email)
    if customer is None or not customer.is_auth or not customer.password:
        raise AuthError("Invalid email or password")
    if not verify_password(password, customer.password):
        raise AuthError("Invalid email or password")

    claims = _build_customer_claims(customer)
    access, refresh, expires_in = _issue_tokens(
        db,
        principal_type="customer",
        principal_id=customer.id,
        base_claims=claims,
        user_agent=user_agent,
        ip=ip,
    )
    return customer, claims, access, refresh, expires_in


def refresh_session(
    db: Session,
    *,
    refresh_token: Optional[str],
    user_agent: Optional[str],
    ip: Optional[str],
) -> tuple[str, str, int]:
    if not refresh_token:
        raise AuthError("Missing refresh token")
    try:
        payload = _decode_refresh_token(refresh_token)
    except jwt.PyJWTError as e:
        raise AuthError(f"Invalid refresh token: {e}")

    jti = payload["jti"]
    principal_type = payload["principal"]
    principal_id = int(payload["id"])

    if not repository.remove_refresh_jti(db, principal_type, principal_id, jti):
        raise AuthError("Refresh token revoked")

    if principal_type == "employee":
        employee = repository.get_employee_by_id(db, principal_id)
        if employee is None or not employee.is_active:
            raise AuthError("Account no longer available")
        base_claims = _build_employee_claims(db, employee)
    elif principal_type == "customer":
        customer = repository.get_customer_by_id(db, principal_id)
        if customer is None or not customer.is_auth:
            raise AuthError("Account no longer available")
        base_claims = _build_customer_claims(customer)
    else:
        raise AuthError("Unknown principal type")

    return _issue_tokens(
        db,
        principal_type=principal_type,
        principal_id=principal_id,
        base_claims=base_claims,
        user_agent=user_agent,
        ip=ip,
    )


def logout(db: Session, *, refresh_token: Optional[str]) -> int:
    if not refresh_token:
        return 0
    try:
        payload = _decode_refresh_token(refresh_token)
    except jwt.PyJWTError:
        return 0
    return repository.remove_refresh_jti(
        db, payload["principal"], int(payload["id"]), payload["jti"]
    )


def logout_all(db: Session, *, principal_type: str, principal_id: int) -> int:
    return repository.clear_refresh_jtis(db, principal_type, principal_id)
