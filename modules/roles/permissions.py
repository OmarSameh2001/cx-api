class PermissionKey:
    RESOURCES = [
        "customers",
        "employees",
        "units",
        "organisations",
        "forms",
        "submissions",
        "assignments",
        "roles",
    ]

    ACTIONS = [
        "read",
        "create",
        "update",
        "delete",
    ]

    @classmethod
    def all_pairs(cls) -> list[tuple[str, str]]:
        return [(resource, action) for resource in cls.RESOURCES for action in cls.ACTIONS]
