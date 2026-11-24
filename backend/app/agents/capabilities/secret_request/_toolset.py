"""The tools the secret-request capability exposes.

One tool, `request_secret`: the agent names a secret it needs and what it
is for, and the run parks on the call until the person supplies the value
through the card - or declines, which ends the run failed rather than
resumed. The value never passes through this tool: it is not an argument,
not a result, and the model never sees it. What the model reads back on
resume names the stored secret and its hint, never the value.
"""

from pydantic_ai.tools import AgentDepsT, RunContext
from pydantic_ai.toolsets import FunctionToolset

from app.agents.capabilities._failures import steer
from app.agents.secret_request import (
    MAX_SECRET_NAME_CHARS,
    MAX_WHAT_FOR_CHARS,
    park_the_secret_request,
)
from app.core.secret_kinds import SecretKind


class SecretRequestToolset(FunctionToolset[AgentDepsT]):
    """Ask the person running the agent for a secret, and wait for it."""

    def __init__(self) -> None:
        super().__init__()
        self.add_function(self.request_secret, name="request_secret")

    async def request_secret(
        self,
        ctx: RunContext[AgentDepsT],
        secret_name: str,
        what_for: str,
        kind: str = "api_key",
    ) -> str:
        """Ask the person for a secret this run needs but does not have.

        Use it when the work needs a credential - an API key, a token - that
        no binding supplies, instead of guessing, working around it, or
        asking for the value in plain chat. Name the secret exactly as it
        should be stored, and say what it is for: the person decides from
        those two lines. The run waits on their answer; if they decline, it
        ends with a failed report rather than carrying on without the secret.

        Do not put a secret value in any argument, and never ask the person
        to paste one into the chat - the card is the only place it goes, and
        the card seals it straight into the vault.

        Args:
            secret_name: The name to store the secret under, e.g. "acme_api_key".
            what_for: What the secret is for, e.g. "Acme CRM, to list contacts".
            kind: The shape of the credential, as the vault names it; "api_key"
                unless the credential has a shape the vault already knows.

        Returns:
            On resume, that the secret was provided and stored, by name - never
            its value. The call itself never returns: it parks the run.
        """
        name = (secret_name or "").strip()
        purpose = (what_for or "").strip()
        if not name:
            return steer(ctx, "Name the secret to store, e.g. 'acme_api_key'.")
        if len(name) > MAX_SECRET_NAME_CHARS:
            return steer(ctx, f"Keep the secret name under {MAX_SECRET_NAME_CHARS} characters.")
        if not purpose:
            return steer(ctx, "Say what the secret is for, so the person can decide.")
        if len(purpose) > MAX_WHAT_FOR_CHARS:
            return steer(ctx, f"Keep what the secret is for under {MAX_WHAT_FOR_CHARS} characters.")
        allowed = ", ".join(item.value for item in SecretKind if item is not SecretKind.NONE)
        try:
            secret_kind = SecretKind(kind)
        except ValueError:
            return steer(ctx, f"Use one of the supported secret kinds: {allowed}.")
        if secret_kind is SecretKind.NONE:
            return steer(ctx, f"Use one of the supported secret kinds: {allowed}.")
        await park_the_secret_request()
        # Unreachable: parking raises. Kept so the function has a return on
        # every path the type checker can see.
        return "Waiting for the person to provide the secret."
