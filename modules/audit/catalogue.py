"""What the audit log records: severities, actions, and the fields tracked
per kind of record. Everything about the audit log that changes as the app
grows is in this file.

- To record a new kind of event, add one line to ACTIONS.
- To give a model a change log, add one Tracked entry to TRACKED (like
  Odoo's `tracking=True`): `audit.snapshot(obj)` before a change and
  `audit.record_changes(db, obj, before)` after it record exactly the tracked
  fields that changed, with their old and new values.
"""

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Optional


class Severity(IntEnum):
    """Stored as a small integer, so "warning and above" is one comparison
    and an index can cover it."""

    DEBUG = 1
    INFO = 2
    NOTICE = 3  # normal but worth noticing: a publish, a new role
    WARNING = 4  # security-relevant: permissions, answer keys, failed sign-ins
    ERROR = 5  # something is probably wrong: many failed sign-ins from one IP
    CRITICAL = 6  # platform-level power changed hands

    @property
    def label(self) -> str:
        return self.name.lower()

    @classmethod
    def parse(cls, value: "str | int | Severity") -> "Severity":
        if isinstance(value, Severity):
            return value
        if isinstance(value, int):
            return cls(value)
        return cls[value.strip().upper()]


@dataclass(frozen=True)
class Action:
    severity: Severity
    label: str


S = Severity

ACTIONS: dict[str, Action] = {
    # --- sign-in ---------------------------------------------------------------
    "auth.login": Action(S.INFO, "Signed in"),
    # raised to ERROR when one IP fails AUDIT_FAILED_LOGIN_ALERT times in a window
    "auth.login_failed": Action(S.WARNING, "Sign-in failed"),
    "auth.login_blocked": Action(S.WARNING, "Sign-in to a disabled account"),
    "auth.logout": Action(S.INFO, "Signed out"),
    "auth.logout_all": Action(S.NOTICE, "Signed out everywhere"),
    # Google, Microsoft... accounts used to sign in (E1.11)
    "auth.identity_linked": Action(S.WARNING, "Sign-in account linked"),
    "auth.identity_unlinked": Action(S.NOTICE, "Sign-in account removed"),
    "auth.identity_link_failed": Action(S.WARNING, "Linking a sign-in account failed"),
    # --- roles and permissions -------------------------------------------------
    "role.created": Action(S.NOTICE, "Role created"),
    "role.updated": Action(S.NOTICE, "Role changed"),
    "role.deleted": Action(S.WARNING, "Role deleted"),
    "role.permissions_changed": Action(S.WARNING, "Role permissions changed"),
    "permission.created": Action(S.NOTICE, "Permission added to the catalogue"),
    "permission.deleted": Action(S.WARNING, "Permission removed from the catalogue"),
    # --- people and structure --------------------------------------------------
    "employee.created": Action(S.NOTICE, "Employee added"),
    "employee.updated": Action(S.INFO, "Employee changed"),
    "employee.deleted": Action(S.WARNING, "Employee removed"),
    "unit.created": Action(S.INFO, "Unit added"),
    "unit.updated": Action(S.INFO, "Unit changed"),
    "unit.deleted": Action(S.NOTICE, "Unit removed"),
    "organisation.created": Action(S.NOTICE, "Organisation created"),
    "organisation.updated": Action(S.NOTICE, "Organisation changed"),
    "organisation.deleted": Action(S.CRITICAL, "Organisation deleted"),
    "organisation.sign_in_settings_changed": Action(S.WARNING, "Sign-in settings changed"),
    # --- forms -----------------------------------------------------------------
    "form.created": Action(S.INFO, "Form created"),
    "form.updated": Action(S.INFO, "Form settings changed"),
    "form.deleted": Action(S.WARNING, "Form deleted"),
    "form.activated": Action(S.NOTICE, "Form turned on"),
    "form.deactivated": Action(S.NOTICE, "Form turned off"),
    "form.published": Action(S.NOTICE, "Form published"),
    "form.answer_key_changed": Action(S.WARNING, "Answer key changed"),
    "form.version_restored": Action(S.INFO, "Old version restored as draft"),
    "form.public_link_rotated": Action(S.NOTICE, "Public link replaced"),
    "form.public_link_revoked": Action(S.NOTICE, "Public link turned off"),
    "form.results_revealed": Action(S.NOTICE, "Results revealed to respondents"),
    # --- submissions -----------------------------------------------------------
    "submission.score_changed": Action(S.WARNING, "Score changed by a regrade"),
    "submission.score_overridden": Action(S.WARNING, "Score overridden by hand"),
    # --- the audit log itself --------------------------------------------------
    "audit.purged": Action(S.INFO, "Old audit entries removed"),
}


@dataclass(frozen=True)
class Tracked:
    """A model with a change log.

    fields:   attributes whose changes are recorded (old and new value).
    hidden:   tracked, but only *that* they changed is recorded, never the
              values: personal data (names, emails, phones) and secrets.
    sets:     list attributes recorded as what was added and removed, not as
              two whole lists (much smaller for long lists).
    escalate: a change to one of these attributes raises the event's
              severity to at least the one given.

    Ids of other records (role_id, unit_id...) are stored as ids; the audit
    screen shows their current names (see service.REFS).
    """

    entity_type: str
    fields: tuple[str, ...]
    hidden: frozenset[str] = frozenset()
    sets: frozenset[str] = frozenset()
    escalate: dict[str, Severity] = field(default_factory=dict)
    organisation_attr: Optional[str] = "organisation_id"
    # the record's name in "created"/"deleted" entries; never personal data
    title_attr: Optional[str] = None


# keyed by model class name, so this file imports no models
TRACKED: dict[str, Tracked] = {
    "Role": Tracked("role", fields=("name", "is_system"), title_attr="name"),
    "Employee": Tracked(
        "employee",
        fields=(
            "first_name", "last_name", "email", "username", "phone", "dob", "gender", "external_id",
            "password", "role_id", "unit_id", "manager_id", "assigned_units", "is_active", "is_platform_admin",
        ),
        hidden=frozenset({
            "first_name", "last_name", "email", "username", "phone", "dob", "gender", "external_id",
            "password",
        }),
        sets=frozenset({"assigned_units"}),
        escalate={"role_id": S.WARNING, "is_active": S.NOTICE, "is_platform_admin": S.CRITICAL},
    ),
    "Unit": Tracked(
        "unit", fields=("name", "type", "parent_unit_id", "is_active", "external_id", "contact_info"),
        # a branch's contact details may be a person's phone or email
        hidden=frozenset({"contact_info"}),
        escalate={"parent_unit_id": S.NOTICE},
        title_attr="name",
    ),
    "Organisation": Tracked(
        "organisation",
        fields=("name", "industry", "logo_file_id", "contact_info", "subscription_plan_id", "subscription_end"),
        hidden=frozenset({"contact_info"}),
        organisation_attr="id",
        title_attr="name",
    ),
    "Form": Tracked(
        "form",
        fields=(
            "name", "description", "type", "is_active", "is_archived", "submitter_type",
            "assigned_to_units", "settings",
        ),
        sets=frozenset({"submitter_type", "assigned_to_units"}),
        escalate={"type": S.NOTICE},
        title_attr="name",
    ),
}


def action(name: str) -> Action:
    try:
        return ACTIONS[name]
    except KeyError:
        raise ValueError(f"unknown audit action {name!r}: add it to modules/audit/catalogue.py") from None


def tracked_for(obj: object) -> Tracked:
    spec = TRACKED.get(type(obj).__name__)
    if spec is None:
        raise ValueError(f"{type(obj).__name__} has no change log: add it to TRACKED")
    return spec


ENTITY_TYPES = sorted({t.entity_type for t in TRACKED.values()} | {"submission", "permission"})
