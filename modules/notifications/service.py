"""Notifications (E1.9): in-app, and messages on other channels sent by the
worker.

Other modules notify people inside their own transaction:

    from modules.notifications import service as notifications
    notifications.notify(
        db, organisation_id=org, recipient_ids=[manager_id], template="task.assigned",
        params={"task": "Call the customer back", "due": "Thursday"}, link="/tasks/12",
        channels=("in_app", "email"),
    )
    db.commit()

That adds an in-app notification and an email delivery per person. The
`notifications.deliver` job sends due deliveries through
common.services.messaging, retrying failures with backoff. Channels with no
provider configured are skipped when notifying, so nothing is queued that
can never be sent.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Iterable, Optional, Sequence

from fastapi import HTTPException, status
from loguru import logger
from sqlalchemy.orm import Session

from common.services import messaging
from config import NotificationsEnv as Env
from modules.auth.dto import EmployeePrincipal

from . import repository, templates
from .dto import (
    ChannelInfo, ChannelResult, ChannelsInfo, MarkedRead, NotificationPage, NotificationRead, TestRequest,
    TestResult,
)
from .model import DELIVERY_CHANNELS, Notification, NotificationDelivery

_MAX_ERROR = 500


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _default_locale() -> str:
    return templates.locale_or_default(Env.NOTIFICATIONS_DEFAULT_LOCALE, "en")


def _address(channel: str, employee) -> Optional[str]:
    if channel == "email":
        return employee.email or None
    if channel in ("sms", "whatsapp"):
        return employee.phone or None
    return None


# --- notifying ----------------------------------------------------------------------


def notify(
    db: Session,
    *,
    organisation_id: int,
    recipient_ids: Sequence[int],
    template: str,
    params: Optional[dict[str, Any]] = None,
    link: Optional[str] = None,
    channels: Iterable[str] = ("in_app",),
    locale: Optional[str] = None,
) -> tuple[list[Notification], list[NotificationDelivery]]:
    """Notifies the organisation's active employees among `recipient_ids`
    on each channel. Slack goes once to the configured channel, not per
    person. Does not commit."""
    if not templates.exists(template):
        raise ValueError(f"unknown notification template {template!r}: add it to templates.py")
    channels = list(dict.fromkeys(channels))
    unknown = set(channels) - {"in_app", *DELIVERY_CHANNELS}
    if unknown:
        raise ValueError(f"unknown channels: {sorted(unknown)}")
    locale = templates.locale_or_default(locale, _default_locale())
    people = repository.recipients(db, organisation_id=organisation_id, employee_ids=recipient_ids)

    in_app: dict[int, Notification] = {}
    if "in_app" in channels:
        for person in people:
            in_app[person.id] = Notification(
                organisation_id=organisation_id, recipient_id=person.id, template=template,
                params=params or None, link=link, created_at=_now(),
            )
        repository.add(db, list(in_app.values()))
        if in_app and any(c in DELIVERY_CHANNELS for c in channels):
            db.flush()  # deliveries point at their notification

    def delivery(channel: str, address: str, person=None) -> NotificationDelivery:
        note = in_app.get(person.id) if person is not None else None
        return NotificationDelivery(
            organisation_id=organisation_id, notification_id=note.id if note else None,
            recipient_id=person.id if person is not None else None, channel=channel, address=address,
            template=template, params=params or None, link=link, locale=locale, status="pending",
            attempts=0, next_attempt_at=_now(), created_at=_now(),
        )

    deliveries: list[NotificationDelivery] = []
    for channel in channels:
        if channel == "in_app" or not messaging.is_enabled(channel):
            continue
        if channel == "slack":
            if people:
                deliveries.append(delivery("slack", ""))
            continue
        for person in people:
            address = _address(channel, person)
            if address:
                deliveries.append(delivery(channel, address, person))
    repository.add(db, deliveries)
    return list(in_app.values()), deliveries


# --- sending ------------------------------------------------------------------------


def _absolute(link: Optional[str]) -> Optional[str]:
    if link and link.startswith("/"):
        return Env.APP_URL + link
    return link


def message_for(row: NotificationDelivery) -> messaging.Message:
    text = templates.render(row.template, row.params, row.locale)
    link = _absolute(row.link)
    common = dict(channel=row.channel, to=row.address, locale=row.locale, reference=f"delivery-{row.id}")
    if row.channel == "email":
        return messaging.Message(
            **common, subject=text.title, text=templates.plain_text(text, link=link),
            html=templates.email_html(text, locale=row.locale, link=link, app_name=Env.APP_NAME),
        )
    if row.channel == "slack":
        return messaging.Message(**common, subject=text.title, text="\n".join(p for p in (text.body, link) if p))
    return messaging.Message(**common, text=templates.short_text(text, link=link))


def _backoff(attempts: int) -> timedelta:
    return timedelta(seconds=min(60 * 2 ** max(0, attempts - 1), Env.NOTIFICATIONS_RETRY_BACKOFF_MAX_SECONDS))


def send_one(row: NotificationDelivery) -> None:
    """Sends a claimed delivery and records how it went. No commit."""
    now = _now()
    try:
        result = messaging.send(message_for(row))
    except messaging.MessagingError as exc:
        row.provider = exc.provider
        row.last_error = str(exc)[:_MAX_ERROR]
        if exc.permanent or row.attempts >= Env.NOTIFICATIONS_MAX_ATTEMPTS:
            row.status = "failed"
            logger.warning("delivery {} ({}) failed for good: {}", row.id, row.channel, exc)
        else:
            row.status = "pending"
            row.next_attempt_at = now + _backoff(row.attempts)
        return
    row.status = "sent"
    row.sent_at = now
    row.provider = result.provider
    row.provider_message_id = result.message_id[:255] if result.message_id else None
    row.last_error = None


def deliver_due(db: Session, *, limit: Optional[int] = None) -> dict[str, int]:
    """One worker run: claims due deliveries (committed, so another worker
    skips them), sends each, and commits each result."""
    counts = {"sent": 0, "failed": 0, "retrying": 0}
    rows = repository.claim_due(
        db, now=_now(), limit=limit or Env.NOTIFICATIONS_DELIVER_BATCH_SIZE,
        hold=timedelta(seconds=Env.NOTIFICATIONS_SENDING_TIMEOUT_SECONDS),
    )
    db.commit()
    for row in rows:
        send_one(row)
        counts["retrying" if row.status == "pending" else row.status] += 1
        db.commit()
    return counts


# --- the bell -----------------------------------------------------------------------


def _read(row: Notification, locale: str) -> NotificationRead:
    text = templates.render(row.template, row.params, locale)
    return NotificationRead(
        id=row.id, template=row.template, title=text.title, body=text.body, link=row.link,
        created_at=row.created_at, read_at=row.read_at,
    )


def list_mine(
    db: Session, *, employee: EmployeePrincipal, before_id: Optional[int], limit: int, unread_only: bool,
    locale: Optional[str],
) -> NotificationPage:
    locale = templates.locale_or_default(locale, _default_locale())
    rows = repository.list_for(db, recipient_id=employee.id, before_id=before_id, limit=limit + 1,
                               unread_only=unread_only)
    more = len(rows) > limit
    rows = rows[:limit]
    return NotificationPage(
        items=[_read(r, locale) for r in rows],
        next_before_id=rows[-1].id if more and rows else None,
        unread=repository.unread_count(db, recipient_id=employee.id),
    )


def unread_count(db: Session, *, employee: EmployeePrincipal) -> int:
    return repository.unread_count(db, recipient_id=employee.id)


def mark_read(db: Session, *, employee: EmployeePrincipal, ids: Optional[Sequence[int]]) -> MarkedRead:
    """Marks the caller's own notifications read (all of them without ids).
    Other people's ids are ignored: nobody can touch another's bell."""
    marked = repository.mark_read(db, recipient_id=employee.id, at=_now(), ids=ids)
    db.commit()
    return MarkedRead(marked=marked, unread=repository.unread_count(db, recipient_id=employee.id))


def mark_unread(db: Session, *, employee: EmployeePrincipal, notification_id: int) -> MarkedRead:
    if not repository.mark_unread(db, recipient_id=employee.id, notification_id=notification_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Notification not found")
    db.commit()
    return MarkedRead(marked=1, unread=repository.unread_count(db, recipient_id=employee.id))


# --- settings and tests (organisation admins) -----------------------------------------


def _ensure_admin(employee: EmployeePrincipal) -> None:
    if not (employee.is_admin or employee.is_platform_admin):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only the organisation admin can do this")


def channels(employee: EmployeePrincipal) -> ChannelsInfo:
    _ensure_admin(employee)
    available = messaging.available()
    return ChannelsInfo(channels=[
        ChannelInfo(channel="in_app", enabled=True, providers=[], available=[]),
        *(
            ChannelInfo(channel=c, enabled=messaging.is_enabled(c), providers=messaging.configured(c),
                        available=available.get(c, []))
            for c in DELIVERY_CHANNELS
        ),
    ])


def send_test(db: Session, *, employee: EmployeePrincipal, payload: TestRequest) -> TestResult:
    """Notifies the caller on each channel asked for and sends at once, so
    the screen can say whether the channel works."""
    _ensure_admin(employee)
    results: list[ChannelResult] = []
    for channel in payload.channels:
        if channel != "in_app" and not messaging.is_enabled(channel):
            results.append(ChannelResult(channel=channel, status="skipped",
                                         detail=f"No {channel} provider is configured ({channel.upper()}_PROVIDERS)"))
            continue
        notes, deliveries = notify(
            db, organisation_id=employee.organisation_id, recipient_ids=[employee.id], template="system.test",
            params={"app": Env.APP_NAME, "channel": channel}, link="/profile",
            channels=[channel], locale=payload.locale,
        )
        if channel == "in_app":
            results.append(ChannelResult(channel=channel, status="sent" if notes else "skipped",
                                         detail=None if notes else "Your account is not active"))
            continue
        if not deliveries:
            results.append(ChannelResult(channel=channel, status="skipped",
                                         detail="Your profile has no address for this channel"))
            continue
        row = deliveries[0]
        db.flush()
        row.status, row.attempts = "sending", 1
        send_one(row)
        results.append(ChannelResult(
            channel=channel, provider=row.provider, detail=row.last_error,
            status={"sent": "sent", "failed": "failed"}.get(row.status, "queued"),
        ))
    db.commit()
    return TestResult(results=results)


# --- retention --------------------------------------------------------------------


def purge(db: Session) -> dict[str, int]:
    now = _now()
    counts = repository.purge(
        db,
        read_before=now - timedelta(days=Env.NOTIFICATIONS_READ_RETENTION_DAYS),
        unread_before=now - timedelta(days=Env.NOTIFICATIONS_UNREAD_RETENTION_DAYS),
        deliveries_before=now - timedelta(days=Env.NOTIFICATIONS_DELIVERY_RETENTION_DAYS),
    )
    db.commit()
    return counts
