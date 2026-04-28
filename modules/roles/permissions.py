from enum import Enum


class PermissionKey(str, Enum):
    CUSTOMERS_READ = "customers:read"
    CUSTOMERS_WRITE = "customers:write"
    EMPLOYEES_READ = "employees:read"
    EMPLOYEES_WRITE = "employees:write"
    UNITS_READ = "units:read"
    UNITS_WRITE = "units:write"
    ORGANISATIONS_READ = "organisations:read"
    ORGANISATIONS_WRITE = "organisations:write"
    FORMS_READ = "forms:read"
    FORMS_WRITE = "forms:write"
    SUBMISSIONS_READ = "submissions:read"
    SUBMISSIONS_WRITE = "submissions:write"
    ASSIGNMENTS_READ = "assignments:read"
    ASSIGNMENTS_WRITE = "assignments:write"
    ROLES_READ = "roles:read"
    ROLES_WRITE = "roles:write"

    def split(self) -> tuple[str, str]:
        resource, action = self.value.split(":", 1)
        return resource, action

    @classmethod
    def all_pairs(cls) -> list[tuple[str, str]]:
        return [member.split() for member in cls]
