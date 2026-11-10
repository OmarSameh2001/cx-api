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
        "mentions",
        "keywords",
        "notification_rules",
        "notification_deliveries",
    ]

    ACTIONS = [
        "read",
        "create",
        "update",
        "delete",
    ]

    # Resources that used to be role permissions and must not be any more.
    PLATFORM_RESOURCES = ["organisations", "tenants"]

    @classmethod
    def all_pairs(cls) -> list[tuple[str, str]]:
        return [(resource, action) for resource in cls.RESOURCES for action in cls.ACTIONS]


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
    (
        "agent",
        False,
        [
            ("customers", "read"),
            ("forms", "read"),
            ("submissions", "read"),
            ("submissions", "create"),
        ],
    ),
]
