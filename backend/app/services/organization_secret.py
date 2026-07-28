"""Organization secrets - storage, rotation, and the one place they are opened.

Everything above this deals in secret ids; everything below deals in ciphertext.
There is deliberately no method that returns a plaintext to a caller who is not
about to build an agent: :meth:`OrganizationSecretService.resolve_for_bindings`
is the only reader, and it is called by the runner.
"""

from __future__ import annotations

from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core import secret_purposes
from app.core.audit import record_audit
from app.core.exceptions import AlreadyExistsError, BadRequestError, NotFoundError
from app.core.permissions import AuthContext, Perm
from app.core.secret_kinds import SecretKind, StorableSecret, seal_secret, unseal_secret
from app.core.secret_purposes import CUSTOM
from app.core.vault import VaultScope
from app.db.models.organization_secret import OrganizationSecret
from app.db.models.resource_grant import Visibility
from app.repositories import member_repo, organization_secret_repo, resource_grant_repo
from app.schemas.resource_grant import as_visibility
from app.schemas.secret import SecretRead, SecretUsage
from app.services.access import SECRET, resolve_access, visible_resource_ids


class OrganizationSecretService:
    """Manage the secrets an organization's capabilities may reference."""

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    @staticmethod
    def _check_purpose(purpose: str, kind: SecretKind) -> None:
        """Refuse a purpose this deployment does not offer, or the wrong shape.

        The shape check is the one that matters: a purpose says which service
        the key is for, and every service knows what a credential for it looks
        like. Storing an AWS pair as an OpenAI key produces a vault entry that
        reads correctly and fails at the first run.
        """
        entry = secret_purposes.get(purpose)
        if entry is None:
            raise BadRequestError(
                message=f"Unknown purpose: {purpose}", details={"purpose": purpose}
            )
        if entry.kind is not kind:
            raise BadRequestError(
                message=(f"{entry.label} needs a {entry.kind.value} credential, not {kind.value}"),
                details={"purpose": purpose, "expected_kind": entry.kind.value},
            )

    async def list_secrets(
        self, ctx: AuthContext, *, purposes: list[str] | None = None
    ) -> list[SecretRead]:
        """The secrets this caller may see, with who put each one there and what
        it is holding up.

        Visibility is resolved here rather than left to the route, because "a
        member sees their own keys and the organization's" is a property of the
        vault and not of one endpoint. `purposes` narrows it further - the
        Tavily keys for a web-search slot, the OpenRouter ones for a model
        picker.

        Both are answered here rather than left to the caller because both are
        the difference between a list of names and a list somebody can act on:
        a key nothing binds is one nobody can account for, and a key whose owner
        has left is one nobody will rotate.

        Two extra queries for the page, not two per row: emails resolve in one
        lookup and usage in one per secret, which is bounded by how many secrets
        an organization has - tens, not thousands.
        """
        # `None` is the role already reaching every key; anything else is the
        # extra ids a grant opened up. One call answers both, so the scope is
        # never read twice and the two answers cannot disagree.
        shared = await visible_resource_ids(
            self.db, ctx, resource_type=SECRET, perm=Perm.SECRETS_VIEW
        )
        secrets = await organization_secret_repo.list_secrets(
            self.db,
            organization_id=ctx.organization_id,
            user_id=ctx.subject_id,
            see_all=shared is None,
            shared_ids=[] if shared is None else shared,
            purposes=purposes,
        )
        people = await member_repo.get_identities_for_users(
            self.db,
            organization_id=ctx.organization_id,
            # Both columns, one lookup: a personal key's owner and whoever
            # stored it are usually the same person and occasionally are not.
            user_ids=[
                user_id
                for secret in secrets
                for user_id in (secret.created_by_user_id, secret.owner_user_id)
                if user_id
            ],
        )
        # How far each key reaches, in one grouped query rather than one per
        # row. A listing that only says "private" cannot distinguish a key
        # nobody else has from one five people were handed.
        shared_counts = await resource_grant_repo.count_for_resources(
            self.db,
            organization_id=ctx.organization_id,
            resource_type=SECRET.key,
            resource_ids=[secret.id for secret in secrets],
        )
        rows: list[SecretRead] = []
        for secret in secrets:
            owner = people.get(secret.owner_user_id) if secret.owner_user_id else None
            author = people.get(secret.created_by_user_id) if secret.created_by_user_id else None
            owner = owner or member_repo.MemberIdentity(email=None, avatar_url=None)
            author = author or member_repo.MemberIdentity(email=None, avatar_url=None)
            used = await organization_secret_repo.agents_using(
                self.db, organization_id=ctx.organization_id, secret_id=secret.id
            )
            rows.append(
                SecretRead(
                    id=secret.id,
                    name=secret.name,
                    description=secret.description,
                    kind=SecretKind(secret.kind),
                    hint=secret.hint,
                    purpose=secret.purpose,
                    visibility=as_visibility(secret.visibility),
                    owner_user_id=secret.owner_user_id,
                    owner_email=owner.email,
                    created_by_email=author.email,
                    created_by_avatar_url=author.avatar_url,
                    shared_with=shared_counts.get(secret.id, 0),
                    used_by=[
                        SecretUsage(kind="agent", id=agent_id, name=name) for agent_id, name in used
                    ],
                    created_at=secret.created_at,
                    updated_at=secret.updated_at,
                )
            )
        return rows

    async def create(
        self,
        ctx: AuthContext,
        *,
        name: str,
        value: StorableSecret,
        description: str | None = None,
        purpose: str = CUSTOM,
        visibility: Visibility = Visibility.ORG,
    ) -> OrganizationSecret:
        """Seal and store a secret.

        `purpose` is what the key is for - a provider, a service, or `custom`.
        It is what lets the model picker offer the providers this organization
        can actually reach, and what lets a capability ask for the right key
        rather than for "an API key".

        `visibility` decides who else sees it. A private key belongs to the
        person who added it; an organization one is the team's. Both are
        legitimate: a shared OpenAI account and somebody's own trial key are
        different things, and forcing either into the other's shape is what the
        single-visibility vault did.

        Raises:
            AlreadyExistsError: If the name is taken. The name plus four
                characters is the whole of what anyone can see of a stored
                secret, so two sharing one is a pair nobody can tell apart -
                including the person about to point an agent at the wrong one.
            BadRequestError: If the purpose is not one this deployment offers,
                or wants a different shape of credential than was given.
        """
        self._check_purpose(purpose, value.kind)
        await self._refuse_duplicate_name(ctx, name)
        sealed = seal_secret(value, scope=VaultScope.organization(ctx.organization_id))
        secret = await organization_secret_repo.create(
            self.db,
            organization_id=ctx.organization_id,
            name=name,
            description=description,
            kind=value.kind.value,
            purpose=purpose,
            visibility=visibility.value,
            # A private key needs an owner or nobody can reach it - the
            # database refuses that combination, and this is where it is made
            # impossible rather than caught.
            owner_user_id=ctx.user_id if visibility is Visibility.PRIVATE else None,
            sealed_secret=sealed.ciphertext,
            hint=sealed.hint,
            key_version=sealed.key_version,
            created_by_user_id=ctx.user_id,
        )
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="secret.created",
            target_type="secret",
            target_id=str(secret.id),
            # The value never reaches the audit log; the hint is what identifies it.
            details={"name": name, "kind": value.kind.value, "hint": sealed.hint},
        )
        return secret

    async def update(
        self,
        ctx: AuthContext,
        secret_id: UUID,
        *,
        name: str | None = None,
        description: str | None = None,
        value: StorableSecret | None = None,
    ) -> OrganizationSecret:
        """Rename, re-describe or rotate a secret.

        A rotation may not change the kind: agents were published against a
        capability that requires one shape, and swapping an API key for an AWS
        key pair under a stable id would break them at run time with nothing
        pointing back at this edit. Changing shape means a new secret.

        Raises:
            NotFoundError: If no such secret exists in this organization.
            BadRequestError: If a rotation would change the secret's kind.
            AlreadyExistsError: If the new name is taken.
        """
        secret = await self._get(ctx, secret_id, perm=Perm.SECRETS_EDIT)
        update_data: dict[str, object] = {}

        if name is not None and name != secret.name:
            await self._refuse_duplicate_name(ctx, name)
            update_data["name"] = name
        if description is not None:
            update_data["description"] = description
        if value is not None:
            self._refuse_kind_change(secret, value)
            sealed = seal_secret(value, scope=VaultScope.organization(ctx.organization_id))
            update_data["sealed_secret"] = sealed.ciphertext
            update_data["hint"] = sealed.hint
            update_data["key_version"] = sealed.key_version

        if not update_data:
            return secret

        secret = await organization_secret_repo.update(
            self.db, secret=secret, update_data=update_data
        )
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="secret.rotated" if value is not None else "secret.updated",
            target_type="secret",
            target_id=str(secret.id),
            details={"name": secret.name, "kind": secret.kind, "hint": secret.hint},
        )
        return secret

    async def delete(self, ctx: AuthContext, secret_id: UUID) -> None:
        """Delete a secret.

        Agents referencing it are not repointed and not blocked from being
        deleted out from under - they fail loudly at their next run, the same
        way a model profile whose key was deleted does. Silently substituting
        another secret is the alternative, and it is worse.
        """
        secret = await self._get(ctx, secret_id, perm=Perm.SECRETS_EDIT)
        await organization_secret_repo.delete(
            self.db, secret_id, organization_id=ctx.organization_id
        )
        await record_audit(
            self.db,
            actor_user_id=ctx.subject_id,
            organization_id=ctx.organization_id,
            action="secret.deleted",
            target_type="secret",
            target_id=str(secret_id),
            details={"name": secret.name, "kind": secret.kind},
        )

    async def resolve_for_bindings(
        self, ctx: AuthContext, secret_ids: list[UUID]
    ) -> dict[UUID, StorableSecret]:
        """Unseal the secrets a run's bindings reference.

        The only reader of a plaintext in the whole service. Ids that no longer
        resolve are simply absent from the result; the capability registry turns
        a missing *required* secret into a refusal, and it is the one place that
        knows which bindings actually needed one.
        """
        rows = await organization_secret_repo.get_many(
            self.db, secret_ids, organization_id=ctx.organization_id
        )
        scope = VaultScope.organization(ctx.organization_id)
        return {
            secret_id: unseal_secret(
                row.sealed_secret,
                kind=SecretKind(row.kind),
                scope=scope,
                key_version=row.key_version,
            )
            for secret_id, row in rows.items()
        }

    async def _get(
        self, ctx: AuthContext, secret_id: UUID, *, perm: Perm = Perm.SECRETS_VIEW
    ) -> OrganizationSecret:
        """One secret the caller may reach, or reported as missing.

        A refusal reads as "not found" so a member cannot probe which keys exist
        by watching 403s turn into 404s - the same rule agents and skills follow.
        """
        secret = await organization_secret_repo.get(
            self.db, secret_id, organization_id=ctx.organization_id
        )
        if secret is None:
            raise NotFoundError(message="Secret not found", details={"secret_id": str(secret_id)})
        allowed = await resolve_access(self.db, ctx, secret, perm, resource_type=SECRET)
        if not allowed:
            raise NotFoundError(message="Secret not found", details={"secret_id": str(secret_id)})
        return secret

    async def _refuse_duplicate_name(self, ctx: AuthContext, name: str) -> None:
        existing = await organization_secret_repo.get_by_name(
            self.db, name, organization_id=ctx.organization_id
        )
        if existing is not None:
            raise AlreadyExistsError(
                message=(
                    f"A secret named '{name}' already exists. The name and the last four "
                    "characters are all anyone can see of a secret, so give this one a name "
                    "that tells them apart - or rotate the existing one if you are replacing it."
                ),
                details={"name": name},
            )

    @staticmethod
    def _refuse_kind_change(secret: OrganizationSecret, value: StorableSecret) -> None:
        if secret.kind != value.kind.value:
            raise BadRequestError(
                message=(
                    f"Secret '{secret.name}' holds a {secret.kind}, and a rotation cannot "
                    "change that - agents were published against the shape it has. Create a "
                    "new secret instead."
                ),
                details={"secret_id": str(secret.id), "kind": secret.kind},
            )
