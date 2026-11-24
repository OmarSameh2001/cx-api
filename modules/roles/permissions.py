class PermissionKey:
    # Permissions an organisation role can hold. Platform administration
    # (organisations, tenants, this catalogue itself) is deliberately absent:
    # it is gated by Employee.is_platform_admin, never by a role.
    RESOURCES = [
        "customers",
        "employees",
        "units",
        "forms",
        "submissions",
        "assignments",
        "roles",
        "audit",
    ]

    ACTIONS = [
        "read",
        "create",
        "update",
        "delete",
    ]

    # Resources that don't take every action. The audit log is written by
    # the app itself, never through the API, so it can only be read.
    RESOURCE_ACTIONS: dict[str, list[str]] = {
        "audit": ["read"],
    }

    # Resources that used to be role permissions and must not be any more.
    PLATFORM_RESOURCES = ["organisations", "tenants"]
    # The Mentions module was dropped and its routers unmounted, so its
    # permissions left the catalogue too.
    DROPPED_RESOURCES = ["mentions", "keywords", "notification_rules", "notification_deliveries"]

    @classmethod
    def all_pairs(cls) -> list[tuple[str, str]]:
        return [
            (resource, action)
            for resource in cls.RESOURCES
            for action in cls.RESOURCE_ACTIONS.get(resource, cls.ACTIONS)
        ]


# Roles every organisation starts with. `None` means every permission in
# PermissionKey. The system role is the organisation admin.
DEFAULT_ROLES: list[tuple[str, bool, list[tuple[str, str]] | None]] = [
    ("admin", True, None),
    (
        "manager",
        False,
        [
            ("customers", "read"),
            ("customers", "create"),
            ("customers", "update"),
            ("employees", "read"),
            ("units", "read"),
            ("forms", "read"),
            ("forms", "create"),
            ("forms", "update"),
            ("submissions", "read"),
            ("submissions", "create"),
            ("submissions", "update"),
        ],
    ),
    # Agents answer forms and see their own submissions (/submissions/mine
    # needs no permission). No submissions:read: that permission means
    # reviewing everyone's submissions, correct exam answers included.
    (
        "agent",
        False,
        [
            ("customers", "read"),
            ("forms", "read"),
        ],
    ),
]
