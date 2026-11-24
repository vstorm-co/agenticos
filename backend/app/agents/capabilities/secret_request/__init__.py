"""Secret request capability - ask the person for a credential, mid-run (#13)."""

from app.agents.capabilities._registry import (
    CapabilityBuildContext,
    CapabilityToolInfo,
    register,
)
from app.agents.capabilities.secret_request._capability import SecretRequestCapability

__all__ = ["SECRET_REQUEST_CAPABILITY_ID", "SecretRequestCapability"]

SECRET_REQUEST_CAPABILITY_ID = "secret_request"


@register(
    id=SECRET_REQUEST_CAPABILITY_ID,
    name="Request a secret",
    category="utility",
    description=(
        "Let the agent ask the person it is working for for a secret it needs "
        "but does not have - an API key, a token - shown as a card naming the "
        "secret and what it is for. The value is sealed into the vault from "
        "the card and the run resumes; the model never sees the value."
    ),
    tools=(
        CapabilityToolInfo(
            id="request_secret",
            description="Ask the person for a secret this run needs but does not have.",
        ),
    ),
)
def _build(ctx: CapabilityBuildContext) -> SecretRequestCapability:
    return SecretRequestCapability()
