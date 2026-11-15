"""Event outbox: emit() inside the data's transaction, relay() afterwards.

emit() only adds a row to the caller's session; the caller's own commit
saves the data and the event together. The relay (a background job) hands
each pending event to its registered handlers, one event per transaction:

- each handler runs in a savepoint with its processed_events row, so a
  handler that succeeded is never run again for that event;
- a handler that fails is retried on a later run with backoff; after
  EVENTS_MAX_ATTEMPTS the event is marked failed and logged to failed_jobs;
- rows are locked with SKIP LOCKED, so two relays never take the same event.
"""

import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from loguru import logger
from sqlalchemy.orm import Session

from common.events.registry import handlers_for
from config import EventsEnv
from modules.jobs import service as jobs_service

from . import repository
from .model import EVENT_TYPES, OutboxEvent

_MAX_ERROR = 2000


def _now() -> datetime:
    return datetime.now(timezone.utc)


def emit(
    db: Session,
    event_type: str,
    *,
    aggregate_type: str,
    aggregate_id: int,
    organisation_id: Optional[int],
    payload: Optional[dict[str, Any]] = None,
) -> OutboxEvent:
    """Records an event in the caller's transaction. Does not commit."""
    if event_type not in EVENT_TYPES:
        raise ValueError(f"unknown event type {event_type!r}")
    if aggregate_id is None:
        raise ValueError("aggregate_id is required: flush before emitting")
    event = OutboxEvent(
        event_type=event_type,
        aggregate_type=aggregate_type,
        aggregate_id=aggregate_id,
        organisation_id=organisation_id,
        payload=payload or {},
    )
    return repository.add_event(db, event)


def _backoff(attempts: int) -> timedelta:
    seconds = min(60 * 2 ** (attempts - 1), EventsEnv.EVENTS_RETRY_BACKOFF_MAX_SECONDS)
    return timedelta(seconds=seconds)


def _process(db: Session, event: OutboxEvent) -> list[tuple[str, BaseException]]:
    """Runs the handlers that haven't finished for this event yet."""
    finished = repository.processed_handlers(db, event.id)
    errors: list[tuple[str, BaseException]] = []
    for name, fn in handlers_for(event.event_type).items():
        if name in finished:
            continue
        try:
            with db.begin_nested():
                fn(db, event)
                repository.mark_processed(db, event.id, name)
        except Exception as exc:
            logger.warning("event {} ({}): handler {} failed: {!r}", event.id, event.event_type, name, exc)
            errors.append((name, exc))
    return errors


def relay(db: Session) -> dict[str, int]:
    started = time.monotonic()
    counts = {"done": 0, "retrying": 0, "failed": 0, "skipped": 0}
    ids = repository.pending_event_ids(db, now=_now(), limit=EventsEnv.EVENTS_RELAY_BATCH_SIZE)
    db.rollback()  # end the read; each event gets its own transaction

    for event_id in ids:
        if time.monotonic() - started > EventsEnv.EVENTS_RELAY_MAX_SECONDS:
            break  # the rest wait for the next run
        event = repository.lock_pending_event(db, event_id)
        if event is None:
            db.rollback()
            counts["skipped"] += 1
            continue

        errors = _process(db, event)
        now = _now()
        given_up: list[tuple[str, BaseException]] = []
        if not errors:
            event.status = "done"
            event.processed_at = now
            counts["done"] += 1
        else:
            event.attempts += 1
            event.last_error = "; ".join(f"{n}: {type(e).__name__}: {e}" for n, e in errors)[:_MAX_ERROR]
            if event.attempts >= EventsEnv.EVENTS_MAX_ATTEMPTS:
                event.status = "failed"
                event.processed_at = now
                given_up = errors
                counts["failed"] += 1
            else:
                event.available_at = now + _backoff(event.attempts)
                counts["retrying"] += 1
        event_type, attempts = event.event_type, event.attempts
        db.commit()

        for name, exc in given_up:
            jobs_service.record_failure(
                db,
                task_id=f"event-{event_id}",
                task_name=f"event:{event_type}:{name}",
                args=(event_id,),
                kwargs={},
                retries=attempts,
                error=exc,
                traceback=None,
            )
    return counts


def purge_old_events(db: Session) -> int:
    cutoff = _now() - timedelta(days=EventsEnv.EVENTS_RETENTION_DAYS)
    return repository.delete_finished_before(db, cutoff)
