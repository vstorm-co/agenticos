"""Which vault key a voice feature may name next to a provider (#1797, #54).

The rules for speech to text and for voice conversations are the same rules, so
they are one function: speech to text checked them in its own settings service
with its own wording, and a second copy for voice would be the copy that drifts.
"""

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import AuthContext, Perm
from app.core.secret_kinds import SecretKind
from app.db.models.resource_grant import Visibility
from app.repositories import organization_secret_repo
from app.services.access import SECRET, resolve_access

_KIND_PHRASE = {
    SecretKind.API_KEY: "an API key",
    SecretKind.AZURE_OPENAI: "an Azure OpenAI key",
}


async def key_problem(
    db: AsyncSession,
    secret_id: UUID,
    *,
    organization_id: UUID,
    provider: str,
    kind: SecretKind,
    feature: str,
    ctx: AuthContext | None,
) -> str | None:
    """What is wrong with naming this key for `feature` on `provider`, or `None`.

    - The key is in this organization's vault. With `ctx` (an agent's publish),
      the caller must also be able to view it - binding a key lends it to
      everyone who can run the agent. A key they cannot view reads like one that
      does not exist, so a refusal cannot enumerate the vault.
    - Without `ctx` (the organization's default, a bot), the key must be
      organization-visible: the platform spends it for everybody.
    - Its kind is `kind`, and its purpose is the provider.
    """
    row = await organization_secret_repo.get(db, secret_id, organization_id=organization_id)
    if row is None or (
        ctx is not None
        and not await resolve_access(db, ctx, row, Perm.SECRETS_VIEW, resource_type=SECRET)
    ):
        return "That key is not in this organization's vault"
    if ctx is None and row.visibility != Visibility.ORG.value:
        return (
            f"'{row.name}' is not visible to the whole organization. A key used here "
            "is spent for everybody, so only an organization-wide key can be chosen"
        )
    # `feature` is the object, never the subject, so its number never decides a verb.
    if row.kind != kind.value:
        return (
            f"'{row.name}' holds a {row.kind}, and {_KIND_PHRASE[kind]} is required for {feature}"
        )
    if row.purpose != provider:
        return (
            f"'{row.name}' is a key for {row.purpose}, and a key for {provider} is required for "
            f"{feature}"
        )
    return None
