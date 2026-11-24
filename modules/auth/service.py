from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import uuid4

import bcrypt
import jwt
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from config import AuthEnv
from modules.audit import service as audit
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
        role = repository.get_role_claims(db, employee.role_id)
        if role is not None:
            role_name, is_admin, permissions = role

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
        "is_platform_admin": bool(employee.is_platform_admin),
        "permissions": permissions,
        "unit_id": employee.unit_id,
        "assigned_unit_ids": assigned_unit_ids,
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
        # never the email itself (personal data, and often a typo of a real one)
        _record_failed_login(
            db, ip, employee, reason="unknown_account" if employee is None else "wrong_password"
        )
        raise AuthError("Invalid email or password")
    if not employee.is_active:
        audit.record(db, "auth.login_blocked", entity=employee, actor_id=None, ip=ip)
        db.commit()
        raise AuthError("Account is disabled", code=status.HTTP_403_FORBIDDEN)

    # saved by _issue_tokens' commit, with the new session
    audit.record(db, "auth.login", entity=employee, actor_id=employee.id, ip=ip)
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


def _record_failed_login(db: Session, ip: Optional[str], employee, *, reason: str) -> None:
    """Saved at once: the request fails, so nothing else will commit it."""
    severity = audit.failed_login_severity(db, ip)
    if employee is None:
        audit.record(db, "auth.login_failed", organisation_id=None, actor_id=None, ip=ip,
                     severity=severity, data={"reason": reason})
    else:
        audit.record(db, "auth.login_failed", entity=employee, actor_id=None, ip=ip,
                     severity=severity, data={"reason": reason})
    db.commit()


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
    principal_id = int(payload["id"])
    if payload["principal"] == "employee":
        employee = repository.get_employee_by_id(db, principal_id)
        if employee is not None:
            # saved only if the session is really revoked (that commits)
            audit.record(db, "auth.logout", entity=employee, actor_id=employee.id)
    return repository.remove_refresh_jti(db, payload["principal"], principal_id, payload["jti"])


def logout_all(db: Session, *, principal_type: str, principal_id: int) -> int:
    if principal_type == "employee":
        employee = repository.get_employee_by_id(db, principal_id)
        if employee is not None:
            audit.record(db, "auth.logout_all", entity=employee, actor_id=employee.id)
    return repository.clear_refresh_jtis(db, principal_type, principal_id)
