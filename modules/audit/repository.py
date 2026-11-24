import base64
import uuid
from datetime import datetime
from typing import Optional, Sequence

from sqlalchemy import and_, delete, func, select, text, tuple_
from sqlalchemy.orm import Session

from modules.employees.model import Employee
from modules.forms.model import Form
from modules.roles.model import Role
from modules.units.model import Unit

from .model import AuditEvent as AE


def encode_cursor(row: AE) -> str:
    raw = f"{row.occurred_at.isoformat()}|{row.id}"
    return base64.urlsafe_b64encode(raw.encode()).decode().rstrip("=")


def decode_cursor(cursor: str) -> tuple[datetime, int]:
    try:
        padded = cursor + "=" * (-len(cursor) % 4)
        when, _, row_id = base64.urlsafe_b64decode(padded.encode()).decode().partition("|")
        return datetime.fromisoformat(when), int(row_id)
    except (ValueError, UnicodeDecodeError) as exc:
        raise ValueError("invalid cursor") from exc


def _escaped(prefix: str) -> str:
    return prefix.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def list_events(
    db: Session,
    *,
    organisation_id: Optional[int],
    min_severity: Optional[int] = None,
    severities: Optional[Sequence[int]] = None,
    actions: Optional[Sequence[str]] = None,
    action_prefix: Optional[str] = None,
    exclude_action_prefixes: Sequence[str] = (),
    entity_type: Optional[str] = None,
    entity_id: Optional[int] = None,
    actor_id: Optional[int] = None,
    correlation_id: Optional[uuid.UUID] = None,
    occurred_from: Optional[datetime] = None,
    occurred_to: Optional[datetime] = None,
    cursor: Optional[str] = None,
    limit: int = 50,
) -> tuple[list[AE], Optional[str]]:
    """Newest first, keyset-paged on (occurred_at, id), so a page deep in the
    log costs the same as the first. `organisation_id` None means
    platform-level entries (no organisation), never "every organisation"."""
    stmt = select(AE)
    if organisation_id is None:
        stmt = stmt.where(AE.organisation_id.is_(None))
    else:
        stmt = stmt.where(AE.organisation_id == organisation_id)
    if min_severity is not None:
        stmt = stmt.where(AE.severity >= min_severity)
    if severities:
        stmt = stmt.where(AE.severity.in_(severities))
    if actions:
        stmt = stmt.where(AE.action.in_(actions))
    if action_prefix:
        stmt = stmt.where(AE.action.like(_escaped(action_prefix) + "%", escape="\\"))
    for prefix in exclude_action_prefixes:
        stmt = stmt.where(AE.action.not_like(_escaped(prefix) + "%", escape="\\"))
    if entity_type:
        stmt = stmt.where(AE.entity_type == entity_type)
    if entity_id is not None:
        stmt = stmt.where(AE.entity_id == entity_id)
    if actor_id is not None:
        stmt = stmt.where(AE.actor_id == actor_id)
    if correlation_id is not None:
        stmt = stmt.where(AE.correlation_id == correlation_id)
    if occurred_from is not None:
        stmt = stmt.where(AE.occurred_at >= occurred_from)
    if occurred_to is not None:
        stmt = stmt.where(AE.occurred_at < occurred_to)
    if cursor:
        when, row_id = decode_cursor(cursor)
        stmt = stmt.where(tuple_(AE.occurred_at, AE.id) < tuple_(when, row_id))
    stmt = stmt.order_by(AE.occurred_at.desc(), AE.id.desc()).limit(limit + 1)
    rows = list(db.execute(stmt).scalars().all())
    more = len(rows) > limit
    rows = rows[:limit]
    return rows, encode_cursor(rows[-1]) if more and rows else None


def names(
    db: Session, *, organisation_id: Optional[int], wanted: dict[str, set[int]]
) -> dict[str, dict[int, str]]:
    """Current names of the records a page mentions, one query per kind,
    limited to the reader's organisation (platform readers: any)."""
    found: dict[str, dict[int, str]] = {}

    def scoped(stmt, model):
        return stmt if organisation_id is None else stmt.where(model.organisation_id == organisation_id)

    if wanted.get("employee"):
        stmt = scoped(
            select(Employee.id, Employee.first_name, Employee.last_name).where(Employee.id.in_(wanted["employee"])),
            Employee,
        )
        found["employee"] = {
            r.id: " ".join(p for p in (r.first_name, r.last_name) if p) or f"#{r.id}" for r in db.execute(stmt)
        }
    for kind, model in (("role", Role), ("unit", Unit), ("form", Form)):
        if wanted.get(kind):
            stmt = scoped(select(model.id, model.name).where(model.id.in_(wanted[kind])), model)
            found[kind] = {r.id: r.name for r in db.execute(stmt)}
    return found


def count_failed_logins(db: Session, *, ip: str, since: datetime) -> int:
    stmt = (
        select(func.count())
        .select_from(AE)
        .where(and_(AE.action == "auth.login_failed", AE.ip == ip, AE.occurred_at >= since))
    )
    return int(db.execute(stmt).scalar_one())


def purge(db: Session, *, severity: int, before: datetime, batch_size: int) -> int:
    """Deletes one severity's entries older than `before`, a batch per
    transaction. The append-only trigger allows DELETE only while
    cx.audit_purge is on, which is set for each batch's transaction alone."""
    total = 0
    while True:
        db.execute(text("SELECT set_config('cx.audit_purge', 'on', true)"))
        batch = (
            select(AE.id)
            .where(AE.severity == severity)
            .where(AE.occurred_at < before)
            .limit(batch_size)
            .scalar_subquery()
        )
        result = db.execute(delete(AE).where(AE.id.in_(batch)))
        db.commit()
        total += result.rowcount or 0
        if (result.rowcount or 0) < batch_size:
            return total
