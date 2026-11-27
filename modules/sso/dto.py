import re
from datetime import datetime
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

_DOMAIN = re.compile(r"^(?=.{1,253}$)(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$")
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")


class ProviderInfo(BaseModel):
    name: str
    label: str


class ProvidersResponse(BaseModel):
    providers: list[ProviderInfo]


class LinkRequest(BaseModel):
    # linking adds a way into the account, so the password is asked again
    password: str = Field(min_length=1, max_length=256)


class LinkStart(BaseModel):
    # open this in the browser (not fetch it): it goes on to the provider
    url: str


class IdentityRead(BaseModel):
    id: int
    provider: str
    label: str
    email: Optional[str] = None
    created_at: datetime
    last_used_at: Optional[datetime] = None


class ProviderPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: bool = True


class SignInSettings(BaseModel):
    """Who in an organisation may sign in with Google, Microsoft...

    Password sign-in is unaffected. With the defaults, any employee whose
    email the provider has verified can sign in with any enabled provider.
    """

    model_config = ConfigDict(extra="forbid")

    # per provider name; a provider not listed is enabled
    providers: dict[str, ProviderPolicy] = Field(default_factory=dict)
    # personal accounts: Gmail, Outlook.com, Hotmail
    allow_personal_accounts: bool = True
    # a first sign-in may link to the employee with the same (verified)
    # email; when off, people link accounts from their profile only
    link_by_email: bool = True
    # when set, the provider's email must be at one of these domains
    allowed_email_domains: list[str] = Field(default_factory=list, max_length=50)
    # Microsoft directories (tenant ids) the organisation trusts. When set,
    # Microsoft work accounts must come from one of them, and their email
    # then counts as verified.
    trusted_microsoft_tenants: list[str] = Field(default_factory=list, max_length=50)

    @field_validator("providers")
    @classmethod
    def _provider_names(cls, value: dict[str, ProviderPolicy]) -> dict[str, ProviderPolicy]:
        if len(value) > 20:
            raise ValueError("too many providers")
        return {k.strip().lower(): v for k, v in value.items() if k.strip()}

    @field_validator("allowed_email_domains")
    @classmethod
    def _domains(cls, value: list[str]) -> list[str]:
        out: list[str] = []
        for raw in value:
            domain = raw.strip().lower().removeprefix("@")
            if not _DOMAIN.match(domain):
                raise ValueError(f"{raw} is not a valid email domain")
            if domain not in out:
                out.append(domain)
        return out

    @field_validator("trusted_microsoft_tenants")
    @classmethod
    def _tenants(cls, value: list[str]) -> list[str]:
        out: list[str] = []
        for raw in value:
            tenant = raw.strip().lower()
            if not _UUID.match(tenant):
                raise ValueError(f"{raw} is not a valid Microsoft tenant ID")
            if tenant not in out:
                out.append(tenant)
        return out

    def provider_enabled(self, name: str) -> bool:
        policy = self.providers.get(name)
        return policy.enabled if policy is not None else True


class SignInSettingsRead(SignInSettings):
    # the providers switched on for the whole app (the only ones that can be used)
    available_providers: list[ProviderInfo] = Field(default_factory=list)
