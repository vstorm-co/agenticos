"""A person's own subscription accounts: what the console shows and sends."""

from pydantic import BaseModel, ConfigDict, Field

from app.clients.subscription_gateway import GatewayProvider
from app.subscription_gateway.contracts import AccountUsage


class SubscriptionAccountRead(BaseModel):
    """One signed-in account; never its tokens."""

    model_config = ConfigDict(from_attributes=True)

    name: str
    provider: str
    label: str | None = None
    email: str | None = None
    status: str | None = None
    disabled: bool = False
    unavailable: bool = False
    model_prefix: str | None = None
    usage: AccountUsage = Field(default_factory=AccountUsage)


class SubscriptionAccountList(BaseModel):
    enabled: bool = Field(description="Whether this deployment runs the subscription gateway.")
    items: list[SubscriptionAccountRead]


class SubscriptionSignInStart(BaseModel):
    provider: GatewayProvider


class SubscriptionSignIn(BaseModel):
    """Where to sign in, and for a device flow the code to enter there."""

    model_config = ConfigDict(from_attributes=True)

    url: str
    state: str
    flow: str | None = None
    user_code: str | None = None
    expires_in: int | None = None


class SubscriptionSignInStatus(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    status: str = Field(description="`wait`, `ok` or `error`.")
    error: str | None = None


class SubscriptionSignInCallback(BaseModel):
    redirect_url: str = Field(min_length=1, max_length=8192)


class SubscriptionModelSelection(BaseModel):
    model: str = Field(min_length=1, max_length=222, pattern=r"^[^\s]+$")
