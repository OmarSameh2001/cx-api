"""Audit log (E1.8): record what happened, and read it back.

Recording happens inside the caller's transaction: `record()` adds an
AuditEvent to the session and the caller's commit saves it with the data it
describes (or neither). Who, from where and in which request come from
common.request_context unless given.

Change logs, Odoo-style, for the models listed in catalogue.TRACKED:

    before = audit.snapshot(role)
    role.name = "Supervisor"
    audit.record_changes(db, role, before)   # role.updated {"name": ["Manager", "Supervisor"]}
    db.commit()

Who reads it: holders of audit:read see their organisation's log; platform
admins may also read platform-level entries (no organisation).
"""

import copy
import json
import uuid
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from enum import Enum
from typing import Any, Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from common import request_context
from config import AuditEnv
from modules.auth.dto import EmployeePrincipal

from . import repository
from .catalogue import ACTIONS, ENTITY_TYPES, Severity, Tracked, action as get_action, tracked_for
from .dto import (
    ActionInfo, AuditCatalogue, AuditEventRead, AuditPage, AuditQuery, Change, EntityInfo, SeverityInfo,
)
from .model import AuditEvent

_UNSET: Any = object()
_HIDDEN = {"hidden": True}
_NESTED_DEPTH = 3


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --- values ---------------------------------------------------------------------


def _short(value: Any, depth: int = 0) -> Any:
    """A value as it's stored in the log: plain JSON, long text cut, long
    lists cut, and anything still too large replaced by its size."""
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        return value if value == value and value not in (float("inf"), float("-inf")) else str(value)
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, Enum):
        return _short(value.value, depth)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, str):
        limit = AuditEnv.AUDIT_MAX_TEXT_CHARS
        return value if len(value) <= limit else value[:limit] + "…"
    if depth > _NESTED_DEPTH:
        return "…"
    if isinstance(value, (list, tuple, set, frozenset)):
        items = list(value)
        limit = AuditEnv.AUDIT_MAX_LIST_ITEMS
        out = [_short(v, depth + 1) for v in items[:limit]]
        if len(items) > limit:
            out.append(f"…(+{len(items) - limit})")
        return out
    if isinstance(value, dict):
        return {str(k): _short(v, depth + 1) for k, v in value.items()}
    return _short(str(value), depth)


def _bounded(value: Any) -> Any:
    value = _short(value)
    size = len(json.dumps(value, ensure_ascii=False, default=str))
    if size > AuditEnv.AUDIT_MAX_VALUE_BYTES:
        return {"too_large": size}
    return value


def value(v: Any) -> Any:
    """A value as the change log stores it, for callers that build their own
    `changes` (e.g. a form's answer key)."""
    return _bounded(v)


def _as_list(value: Any) -> list:
    if value is None:
        return []
    if isinstance(value, (list, tuple, set, frozenset)):
        return list(value)
    return [value]


def _same(a: Any, b: Any) -> bool:
    if a is None and b is None:
        return True
    try:
        return a == b
    except Exception:
        return False


def _diff_value(changes: dict, key: str, old: Any, new: Any, spec: Tracked, field: str, depth: int) -> None:
    if _same(old, new):
        return
    if field in spec.hidden:
        changes[key] = dict(_HIDDEN)
        return
    if field in spec.sets:
        before, after = _as_list(old), _as_list(new)
        added = [v for v in after if v not in before]
        removed = [v for v in before if v not in after]
        if added or removed:
            changes[key] = {"added": _bounded(added), "removed": _bounded(removed)}
        return
    # settings-like documents: one entry per changed leaf, as a dotted key
    if isinstance(old, dict) and isinstance(new, dict) and depth < _NESTED_DEPTH:
        for k in sorted(set(old) | set(new), key=str):
            _diff_value(changes, f"{key}.{k}", old.get(k), new.get(k), spec, field, depth + 1)
        return
    changes[key] = [_bounded(old), _bounded(new)]


def diff(spec: Tracked, before: dict[str, Any], after: dict[str, Any]) -> dict[str, Any]:
    """The change log between two snapshots: only the tracked fields that
    differ, in the stored format (see AuditEvent.changes)."""
    changes: dict[str, Any] = {}
    for field in spec.fields:
        _diff_value(changes, field, before.get(field), after.get(field), spec, field, 0)
    return changes


def snapshot(obj: object) -> dict[str, Any]:
    """The tracked fields of a record, before a change."""
    spec = tracked_for(obj)
    return {f: copy.deepcopy(getattr(obj, f, None)) for f in spec.fields}


# --- recording ------------------------------------------------------------------


def _organisation_of(obj: object, spec: Tracked) -> Optional[int]:
    return getattr(obj, spec.organisation_attr, None) if spec.organisation_attr else None


def record(
    db: Session,
    action: str,
    *,
    entity: object = None,
    entity_type: Optional[str] = None,
    entity_id: Optional[int] = None,
    organisation_id: Optional[int] = _UNSET,
    actor_id: Optional[int] = _UNSET,
    severity: "Severity | str | None" = None,
    changes: Optional[dict[str, Any]] = None,
    data: Optional[dict[str, Any]] = None,
    ip: Optional[str] = _UNSET,
) -> AuditEvent:
    """Adds an entry to the caller's session. Does not commit.

    `entity` is a tracked record (its type, id and organisation are read
    from it); otherwise name the entity with entity_type and entity_id. The
    organisation, actor and IP default to the current request's."""
    definition = get_action(action)
    ctx = request_context.current()
    if entity is not None:
        spec = tracked_for(entity)
        entity_type = entity_type or spec.entity_type
        entity_id = entity_id if entity_id is not None else getattr(entity, "id", None)
        if organisation_id is _UNSET:
            organisation_id = _organisation_of(entity, spec)
    if organisation_id is _UNSET:
        organisation_id = ctx.organisation_id
    event = AuditEvent(
        occurred_at=_now(),
        organisation_id=organisation_id,
        severity=int(Severity.parse(severity) if severity is not None else definition.severity),
        action=action,
        entity_type=entity_type,
        entity_id=entity_id,
        actor_id=ctx.actor_id if actor_id is _UNSET else actor_id,
        ip=ctx.ip if ip is _UNSET else ip,
        correlation_id=ctx.correlation_id,
        changes=changes or None,
        data=_bounded(data) if data else None,
    )
    db.add(event)
    return event


def _escalated(spec: Tracked, action: str, changes: dict[str, Any]) -> Severity:
    severity = get_action(action).severity
    for key in changes:
        field = key.split(".", 1)[0]
        if field in spec.escalate:
            severity = max(severity, spec.escalate[field])
    return severity


def record_changes(
    db: Session,
    obj: object,
    before: dict[str, Any],
    *,
    action: Optional[str] = None,
    data: Optional[dict[str, Any]] = None,
) -> Optional[AuditEvent]:
    """Records what changed on a tracked record since `before` (a snapshot):
    "<entity>.updated" by default. Records nothing when no tracked field
    changed."""
    spec = tracked_for(obj)
    changes = diff(spec, before, snapshot(obj))
    if not changes:
        return None
    action = action or f"{spec.entity_type}.updated"
    return record(db, action, entity=obj, changes=changes, data=data,
                  severity=_escalated(spec, action, changes))


def _title(obj: object, spec: Tracked) -> Optional[dict[str, Any]]:
    if spec.title_attr and getattr(obj, spec.title_attr, None):
        return {"title": _short(getattr(obj, spec.title_attr))}
    return None


def record_created(db: Session, obj: object, *, data: Optional[dict[str, Any]] = None) -> AuditEvent:
    """"<entity>.created", with the tracked fields it was created with. The
    record needs its id, so it is flushed first if it has none."""
    spec = tracked_for(obj)
    if getattr(obj, "id", None) is None:
        db.flush()
    changes = diff(spec, {}, snapshot(obj))
    action = f"{spec.entity_type}.created"
    return record(db, action, entity=obj, changes=changes,
                  data={**(_title(obj, spec) or {}), **(data or {})} or None,
                  severity=_escalated(spec, action, changes))


def record_deleted(db: Session, obj: object, *, data: Optional[dict[str, Any]] = None) -> AuditEvent:
    """"<entity>.deleted", with the tracked values it had (call it before
    the row is gone)."""
    spec = tracked_for(obj)
    changes = diff(spec, snapshot(obj), {})
    return record(db, f"{spec.entity_type}.deleted", entity=obj, changes=changes,
                  data={**(_title(obj, spec) or {}), **(data or {})} or None)


def failed_login_severity(db: Session, ip: Optional[str]) -> Severity:
    """WARNING, or ERROR once this IP has failed AUDIT_FAILED_LOGIN_ALERT
    times within the window (this attempt included)."""
    if not ip:
        return Severity.WARNING
    since = _now() - timedelta(minutes=AuditEnv.AUDIT_FAILED_LOGIN_WINDOW_MINUTES)
    earlier = repository.count_failed_logins(db, ip=ip, since=since)
    return Severity.ERROR if earlier + 1 >= AuditEnv.AUDIT_FAILED_LOGIN_ALERT else Severity.WARNING


# --- reading --------------------------------------------------------------------


def _changes(raw: Optional[dict[str, Any]]) -> list[Change]:
    out = []
    for key, value in (raw or {}).items():
        if isinstance(value, list) and len(value) == 2:
            out.append(Change(field=key, kind="value", old=value[0], new=value[1]))
        elif isinstance(value, dict) and value.get("hidden"):
            out.append(Change(field=key, kind="hidden"))
        elif isinstance(value, dict) and ("added" in value or "removed" in value):
            out.append(Change(field=key, kind="set", added=value.get("added") or [],
                              removed=value.get("removed") or []))
        else:
            out.append(Change(field=key, kind="value", old=None, new=value))
    return out


def _refs_wanted(rows: list[AuditEvent]) -> dict[str, set[int]]:
    """Ids the page mentions, by kind, so their names can be shown."""
    wanted: dict[str, set[int]] = {"employee": set(), "role": set(), "unit": set(), "form": set()}

    def add(kind: Optional[str], value: Any) -> None:
        if kind in wanted:
            for v in _as_list(value):
                if isinstance(v, int) and not isinstance(v, bool):
                    wanted[kind].add(v)

    for row in rows:
        add("employee", row.actor_id)
        add(row.entity_type, row.entity_id)
        refs = REFS.get(row.entity_type or "", {})
        for key, value in (row.changes or {}).items():
            kind = refs.get(key)
            if kind is None:
                continue
            if isinstance(value, list):
                for v in value:
                    add(kind, v)
            elif isinstance(value, dict):
                add(kind, value.get("added"))
                add(kind, value.get("removed"))
    return wanted


# Changed fields that hold ids of other records, so the screen can show
# their names (looked up when read, within the reader's organisation).
REFS: dict[str, dict[str, str]] = {
    "employee": {"role_id": "role", "unit_id": "unit", "manager_id": "employee", "assigned_units": "unit"},
    "unit": {"parent_unit_id": "unit"},
    "form": {"assigned_to_units": "unit"},
}


def query(db: Session, *, organisation_id: Optional[int], payload: AuditQuery) -> AuditPage:
    """One organisation's log, or with organisation_id None the platform's
    (entries without an organisation: platform actions, sign-ins to unknown
    accounts). The route decides which the caller may read."""
    try:
        rows, next_cursor = _list(db, organisation_id, payload)
    except ValueError as exc:  # a cursor that isn't one of ours
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    return _page(db, organisation_id, rows, next_cursor)


def _page(db: Session, organisation_id: Optional[int], rows: list[AuditEvent], next_cursor: Optional[str]) -> AuditPage:
    names = repository.names(db, organisation_id=organisation_id, wanted=_refs_wanted(rows))
    return AuditPage(
        items=[_read(r) for r in rows],
        next_cursor=next_cursor,
        names={kind: {str(k): v for k, v in found.items()} for kind, found in names.items() if found},
    )


# Sign-ins and sign-outs are activity, not changes to the record: they stay
# in the audit log, for audit:read holders only.
_HISTORY_EXCLUDES = ("auth.",)


def record_history(
    db: Session, *, employee: EmployeePrincipal, entity_type: str, entity_id: int,
    cursor: Optional[str], limit: int,
) -> AuditPage:
    """One record's change log, Odoo-style, for anyone who may open the
    record (see access.py). Callers without audit:read don't get the IP
    address and request id of each change."""
    from . import access

    allowed = access.check(db, employee, entity_type, entity_id)
    organisation_id = allowed.organisation_id
    try:
        rows, next_cursor = repository.list_events(
            db, organisation_id=organisation_id, entity_type=entity_type, entity_id=entity_id,
            exclude_action_prefixes=_HISTORY_EXCLUDES, cursor=cursor, limit=limit,
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(exc)) from exc
    page = _page(db, organisation_id, rows, next_cursor)
    for item in page.items:
        if item.action in allowed.masked_actions:
            item.changes = [Change(field=c.field, kind="hidden") for c in item.changes]
            item.data = {k: v for k, v in (item.data or {}).items() if k != "questions"} or None
        if "audit:read" not in (employee.permissions or []):
            item.ip = None
            item.correlation_id = None
    return page


def _list(db: Session, organisation_id: Optional[int], payload: AuditQuery):
    return repository.list_events(
        db,
        organisation_id=organisation_id,
        min_severity=int(Severity.parse(payload.min_severity)) if payload.min_severity else None,
        severities=[int(Severity.parse(s)) for s in payload.severities] if payload.severities else None,
        actions=payload.actions,
        action_prefix=payload.action_prefix,
        entity_type=payload.entity_type,
        entity_id=payload.entity_id,
        actor_id=payload.actor_id,
        correlation_id=payload.correlation_id,
        occurred_from=payload.occurred_from,
        occurred_to=payload.occurred_to,
        cursor=payload.cursor,
        limit=payload.limit,
    )


def _read(r: AuditEvent) -> AuditEventRead:
    return AuditEventRead(
        id=r.id,
        occurred_at=r.occurred_at,
        organisation_id=r.organisation_id,
        severity=Severity(r.severity).label,
        action=r.action,
        # an action renamed or removed from the catalogue still reads
        action_label=ACTIONS[r.action].label if r.action in ACTIONS else r.action,
        entity_type=r.entity_type,
        entity_id=r.entity_id,
        actor_id=r.actor_id,
        ip=str(r.ip) if r.ip is not None else None,
        correlation_id=r.correlation_id,
        changes=_changes(r.changes),
        data=r.data,
    )


def catalogue() -> AuditCatalogue:
    return AuditCatalogue(
        severities=[SeverityInfo(name=s.label, level=int(s)) for s in Severity],
        actions=[ActionInfo(name=n, label=a.label, severity=a.severity.label) for n, a in ACTIONS.items()],
        entity_types=[EntityInfo(name=t) for t in ENTITY_TYPES],
    )


# --- retention ------------------------------------------------------------------


def purge(db: Session) -> dict[str, int]:
    """Deletes entries older than their severity's retention
    (AUDIT_RETENTION_DAYS_*), in batches, and records how many went."""
    counts: dict[str, int] = {}
    now = _now()
    for severity in Severity:
        days = AuditEnv.AUDIT_RETENTION_DAYS.get(severity.label, 0)
        if days <= 0:
            continue
        deleted = repository.purge(
            db, severity=int(severity), before=now - timedelta(days=days),
            batch_size=AuditEnv.AUDIT_PURGE_BATCH_SIZE,
        )
        if deleted:
            counts[severity.label] = deleted
    if counts:
        record(db, "audit.purged", organisation_id=None, actor_id=None, ip=None, data=counts)
        db.commit()
    return counts
