"""Personal connection actions never accept an owner identity from request data."""

from app.core.claude_subscription import ClaudeSubscriptionOwner
from app.core.exceptions import AuthorizationError, ConflictError
from app.core.permissions import AuthContext
from app.schemas.claude_subscription import ClaudeSubscriptionRead
from app.services.claude_subscription._client import ClaudeSubscriptionRuntime


def subscription_owner(ctx: AuthContext) -> ClaudeSubscriptionOwner:
    """Refuse delegated, unattended and impersonated origins before contacting the runtime."""
    user_id = ctx.personal_user_id
    if user_id is None:
        raise AuthorizationError(
            message="A Claude subscription connection requires its signed-in owner"
        )
    return ClaudeSubscriptionOwner(organization_id=ctx.organization_id, user_id=user_id)


class ClaudeSubscriptionService:
    def __init__(self, runtime: ClaudeSubscriptionRuntime | None = None) -> None:
        self.runtime = runtime if runtime is not None else ClaudeSubscriptionRuntime()

    async def status(self, ctx: AuthContext) -> ClaudeSubscriptionRead:
        return await self.runtime.status(subscription_owner(ctx))

    async def require_connected(self, ctx: AuthContext) -> ClaudeSubscriptionOwner:
        owner = subscription_owner(ctx)
        state = await self.runtime.status(owner)
        if not state.available or not state.connected:
            raise ConflictError(
                message="Connect your Claude subscription in AI connections before adding or using this model",
                code="CLAUDE_NOT_CONNECTED",
            )
        return owner
