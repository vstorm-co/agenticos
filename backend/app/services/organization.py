import contextlib
import logging
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import (
    AlreadyExistsError,
    AuthorizationError,
    BadRequestError,
    ConcurrentChangeError,
    NotFoundError,
)
from app.core.field_errors import refused_field
from app.core.permissions import AuthContext, OrgRoleName, Perm, role_has
from app.db.locks import LockScope, hold_name, hold_subject, try_hold_name
from app.db.models.knowledge_base import KnowledgeBase
from app.db.models.organization import Organization, OrganizationMember, OrgRole
from app.repositories import (
    collection_teardown_repo,
    credential_repo,
    invitation_repo,
    knowledge_base_repo,
    member_repo,
    organization_repo,
    rag_document_repo,
)
from app.schemas.organization import (
    OrganizationCreate,
    OrganizationList,
    OrganizationRead,
    OrganizationUpdate,
)
from app.services import skill_library, speech_to_text
from app.services.deployment_settings import DeploymentSettingsService
from app.services.file_storage import avatar_filename, get_file_storage
from app.services.invitation_admission import admits
from app.services.proactive import ProactiveService
from app.services.skills import SkillService
from app.services.speech_to_text_settings import SpeechToTextSettingsService
from app.worker.jobs import Restamp

if TYPE_CHECKING:
    from app.services.rag.vectorstore import BaseVectorStore

logger = logging.getLogger(__name__)

# The platform's own initiative: spending, so gated like a budget (#2301).
_PROACTIVE_FIELDS = frozenset(
    {
        "proactive_enabled",
        "proactive_model_profile_id",
        "proactive_days",
        "proactive_hour",
        "proactive_timing",
        "proactive_watches_enabled",
        "proactive_watch_min_minutes",
    }
)
_WELCOME_FIELDS = frozenset({"welcome_dm_enabled", "welcome_dm_text"})

_SPEECH_FIELDS = frozenset(
    {
        "speech_to_text_provider",
        "speech_to_text_model",
        "speech_to_text_secret_id",
        "speech_to_text_language",
        "dictation_max_seconds",
    }
)
"""The organization's speech-to-text default (#1797), validated together when any is named."""


def _org_read(
    org: Organization, member_count: int, role: str, *, is_default: bool = False
) -> OrganizationRead:
    """One organization as a member of it sees it.

    `member_count` and `role` are not on the row - the first is a count over
    the membership table, the second is the caller's own membership - so every
    response has to carry them in alongside it. `is_default` is the deployment's
    setting, which is not on the row either.
    """
    return OrganizationRead(
        id=org.id,
        name=org.name,
        slug=org.slug,
        is_personal=org.is_personal,
        is_default=is_default,
        avatar_url=org.avatar_url,
        avatar_color=org.avatar_color,
        member_count=member_count,
        role=role,
        monthly_budget_usd=org.monthly_budget_usd,
        proactive_limit_usd=org.proactive_limit_usd,
        proactive_enabled=org.proactive_enabled,
        proactive_model_profile_id=org.proactive_model_profile_id,
        proactive_days=org.proactive_days,
        proactive_hour=org.proactive_hour,
        proactive_timing=org.proactive_timing,
        proactive_watches_enabled=org.proactive_watches_enabled,
        proactive_watch_min_minutes=org.proactive_watch_min_minutes,
        welcome_dm_enabled=org.welcome_dm_enabled,
        welcome_dm_text=org.welcome_dm_text,
        chat_may_waive_approvals=org.chat_may_waive_approvals,
        speech_to_text_provider=org.speech_to_text_provider,
        speech_to_text_model=org.speech_to_text_model,
        speech_to_text_secret_id=org.speech_to_text_secret_id,
        speech_to_text_language=org.speech_to_text_language,
        dictation_max_seconds=org.dictation_max_seconds,
        created_at=org.created_at,
        updated_at=org.updated_at,
    )


class OrganizationService:
    _ALLOWED_AVATAR_TYPES = {"image/jpeg", "image/png", "image/webp", "image/gif"}

    def __init__(self, db: AsyncSession, vector_store: BaseVectorStore | None = None):
        self.db = db
        # Present only on the teardown path, where the request built a store to
        # drop the tenant's vector tables with; None everywhere else, so ordinary
        # org operations do not pay for one they never use (#9).
        self._vector_store = vector_store

    async def get_by_id(self, org_id: UUID) -> Organization:
        org = await organization_repo.get_by_id(self.db, org_id)
        if not org:
            raise NotFoundError(message="Organization not found", details={"org_id": str(org_id)})
        return org

    async def get_for_user(
        self, org_id: UUID, user_id: UUID
    ) -> tuple[Organization, OrganizationMember]:
        """Get org and verify current user is a member. Returns (org, membership)."""
        membership = await member_repo.get(self.db, organization_id=org_id, user_id=user_id)
        if not membership:
            raise NotFoundError(message="Organization not found", details={"org_id": str(org_id)})
        org = await organization_repo.get_by_id(self.db, org_id)
        if not org:
            raise NotFoundError(message="Organization not found", details={"org_id": str(org_id)})
        return org, membership

    async def read_for_user(self, org_id: UUID, user_id: UUID) -> OrganizationRead:
        """One organization, shaped for the member asking for it.

        Every route answering with a single organization ends here, including
        the ones that just changed it: a PATCH answers with the row as it now
        stands, and its member count and the caller's role are part of that.
        Two of them used to reach that by listing *every* organization the
        caller belongs to and scanning for the one they already held - a query
        per organization, to re-find one row.
        """
        org, membership = await self.get_for_user(org_id, user_id)
        count = await organization_repo.count_members(self.db, org_id)
        default_id = await self._default_organization_id()
        return _org_read(
            org, member_count=count, role=membership.role, is_default=org.id == default_id
        )

    async def list_readable_for_user(self, user_id: UUID) -> OrganizationList:
        """Every organization the caller belongs to, each with role and size."""
        rows = await self.list_for_user(user_id)
        default_id = await self._default_organization_id()
        items = [
            _org_read(
                row["org"],
                row["member_count"],
                row["role"],
                is_default=row["org"].id == default_id,
            )
            for row in rows
        ]
        return OrganizationList(items=items, total=len(items))

    async def list_for_user(self, user_id: UUID) -> list[dict]:
        # Role and member count in two grouped queries, not two per organization:
        # the role rides the membership join the listing already makes, and the
        # counts come back keyed by organization (#953).
        pairs = await organization_repo.list_for_user(self.db, user_id)
        counts = await organization_repo.member_counts_for(self.db, [org.id for org, _ in pairs])
        return [
            {"org": org, "role": role, "member_count": counts.get(org.id, 0)} for org, role in pairs
        ]

    async def create(self, data: OrganizationCreate, owner_id: UUID) -> Organization:
        """Create a new team organization (non-personal).

        Raises:
            AlreadyExistsError: If the slug is taken.
            BadRequestError: If this account already owns as many organizations
                as the deployment allows. Null is no ceiling, which is what a
                deployment that has never set one has - see
                `DeploymentSettings.max_organizations_per_user`.
        """
        await self.refuse_past_the_ceiling(owner_id)
        slug = data.slug
        if slug:
            if await organization_repo.slug_exists(self.db, slug):
                raise AlreadyExistsError(
                    message=(
                        f"The slug '{slug}' is taken. It is this organization's address in URLs "
                        "and has to be unique across the platform - pick a different one, or "
                        "leave it blank and one will be derived from the name."
                    ),
                    details={"slug": slug},
                )
        else:
            slug = await organization_repo.generate_unique_slug(self.db, data.name)

        org = await organization_repo.create(
            self.db,
            name=data.name,
            slug=slug,
            created_by_user_id=owner_id,
            is_personal=False,
            monthly_budget_usd=settings.DEFAULT_ORG_MONTHLY_BUDGET_USD,
        )
        await member_repo.create(
            self.db,
            organization_id=org.id,
            user_id=owner_id,
            role=OrgRole.OWNER.value,
        )
        await self._seed_bundled_skills(org.id, owner_id)
        return org

    async def _seed_bundled_skills(self, organization_id: UUID, owner_id: UUID) -> None:
        """Copy every bundled skill into a brand-new organization.

        Implicit rather than an Install click (#281): a spec binds a skill by
        row id, so a bundled skill has to be a row before the Builder can offer
        it - and gating that row behind a per-person Install button meant two
        lists on the skills page and a step with no decision in it. Seeded as
        the owner with organization visibility, the same shape `seed-skills`
        writes. They are ordinary rows from that moment: an organization that
        does not want one deletes it, and nothing puts it back.
        """
        service = SkillService(self.db)
        ctx = AuthContext(
            user_id=owner_id,
            organization_id=organization_id,
            role=OrgRoleName.OWNER,
        )
        for bundled in skill_library.library():
            try:
                await service.install_from_library(ctx, bundled.key)
            except AlreadyExistsError:
                # Two bundled folders declaring one name - nothing validates the
                # library's own uniqueness. Skipping the twin keeps a packaging
                # mistake from refusing every registration on the deployment;
                # the seed-skills command tolerates the same collision.
                logger.warning("Bundled skill %r shares a name with another; skipped", bundled.key)

    async def refuse_past_the_ceiling(self, owner_id: UUID) -> None:
        """Refuse a transition that would put this account over the deployment's limit.

        Checked here rather than at the route, because the route is not the only
        way in - and the refusal names the ceiling, so the answer to "why can I
        not" is in the response rather than in an administrator's memory.

        **Every transition into ownership calls it, not only a create.**
        `MemberService.transfer_ownership` makes an existing member an owner, and a
        ceiling enforced on new rows alone is one an account at its limit walks past
        by being handed somebody else's organization.

        The personal organization sign-up creates counts, which is why the
        schema refuses a ceiling of zero: an account that cannot own its own
        personal organization is an account that cannot be created.

        The lock is what makes the count mean anything. Read and acted on without
        one, two requests both pass it and both write - the ceiling is exceeded
        deterministically by clicking twice - and no constraint can express "at most
        five rows like this". Taken only where a limit exists, so an uncapped
        deployment pays nothing for it, and released by the transaction either way.
        """
        limit = (await DeploymentSettingsService(self.db).limits()).organizations_per_user
        if limit is None:
            return
        await hold_subject(self.db, LockScope.ORGANIZATIONS_PER_USER, owner_id)
        owned = await organization_repo.count_owned_by(self.db, owner_id)
        if owned >= limit:
            raise BadRequestError(
                message=(
                    f"This deployment allows {limit} organizations per account, and you own "
                    f"{owned}. Ask an administrator to raise the limit, or leave one you no "
                    "longer need."
                ),
                details={"limit": limit, "owned": owned},
            )

    async def _default_organization_id(self) -> UUID | None:
        placement = await DeploymentSettingsService(self.db).new_account_placement()
        return placement.default_organization_id

    async def settle_new_account(
        self,
        user_id: UUID,
        email: str,
        *,
        invitation_token: str | None = None,
        admitted_by_policy: bool = True,
    ) -> None:
        """Give an account created just now the organizations the deployment says it starts in.

        Its own, unless the deployment has turned personal organizations off, and
        the default organization when one is set (#2156). Both account-creation
        paths - the sign-up form and a first sign-in through a provider - end here,
        so neither can place a person somewhere the other would not.

        The default organization only for an account the deployment's own rule
        admitted. One admitted solely by another organization's invitation or
        directory mapping was vouched for by that organization's managers, and
        joining it to the default one would let them add people to an
        organization they cannot manage.
        """
        placement = await DeploymentSettingsService(self.db).new_account_placement()
        if placement.personal:
            await self.create_personal_org(user_id, email)
        if placement.default_organization_id is not None and admitted_by_policy:
            await self._join_default(
                user_id,
                email,
                placement.default_organization_id,
                role=placement.role,
                invitation_token=invitation_token,
            )

    async def _join_default(
        self,
        user_id: UUID,
        email: str,
        organization_id: UUID,
        *,
        role: str,
        invitation_token: str | None,
    ) -> None:
        """Join the default organization, unless an invitation to it is about to.

        An invitation names its own role, and accepting one into an organization
        the person already joined is refused as "already a member" - so a
        newcomer invited as an admin would end up a member, with an invitation
        that no longer works. The invitation wins: the person joins when they
        accept it.
        """
        invitations = [
            await invitation_repo.get_by_token(self.db, invitation_token)
            if invitation_token is not None
            else None,
            await invitation_repo.get_pending_for_org_email(
                self.db, organization_id=organization_id, email=email
            ),
        ]
        # Only an invitation the person can still accept stands in for the join:
        # one past its expiry, used up or revoked would leave them in nothing.
        if any(
            invitation is not None
            and invitation.organization_id == organization_id
            and admits(invitation, email=email)
            for invitation in invitations
        ):
            return
        await member_repo.create(
            self.db, organization_id=organization_id, user_id=user_id, role=role
        )
        await ProactiveService(self.db).queue_welcome(organization_id, user_id)

    async def fallback_for(self, user_id: UUID) -> Organization | None:
        """The organization a session acts in when the request names none.

        The default organization when the person belongs to it, then their
        personal one, then their only organization. `None` when that still leaves
        a choice - two organizations and neither of them default or personal -
        because guessing would be a request quietly acting in a tenant its
        sender never meant (#2156).
        """
        default_id = await self._default_organization_id()
        if default_id is not None and await member_repo.get(
            self.db, organization_id=default_id, user_id=user_id
        ):
            return await organization_repo.get_by_id(self.db, default_id)
        personal = await organization_repo.get_personal_for_user(self.db, user_id)
        if personal is not None:
            return personal
        memberships = await organization_repo.list_for_user(self.db, user_id)
        if len(memberships) == 1:
            return memberships[0][0]
        return None

    async def create_personal_org(self, user_id: UUID, email: str) -> Organization:
        """Create the Personal Organization for a newly registered user.

        It starts with the deployment's default monthly budget
        (`DEFAULT_ORG_MONTHLY_BUDGET_USD`, $100 unless configured otherwise), so
        a fresh account is not one runaway agent away from a surprise bill. A
        deployment that would rather start uncapped sets that to nothing.
        """
        slug = await organization_repo.generate_unique_slug(self.db, email.split("@")[0])
        org = await organization_repo.create(
            self.db,
            name="Personal",
            slug=slug,
            created_by_user_id=user_id,
            is_personal=True,
            monthly_budget_usd=settings.DEFAULT_ORG_MONTHLY_BUDGET_USD,
        )
        await member_repo.create(
            self.db,
            organization_id=org.id,
            user_id=user_id,
            role=OrgRole.OWNER.value,
        )
        await self._seed_bundled_skills(org.id, user_id)
        return org

    async def update(
        self,
        org_id: UUID,
        data: OrganizationUpdate,
        requester_id: UUID,
        key_scopes: frozenset[Perm] | None = None,
    ) -> Organization:
        """Update org metadata and settings.

        Three permissions decide this PATCH, each covering the fields it names:
        `org:settings` for the metadata (name, avatar), `budgets:manage` for
        the monthly spending cap, `approvals:decide` for whether chat sessions
        may waive approvals. The built-in Owner and Admin hold all three, so
        nothing changes for them - but the catalog advertises each as its own
        entitlement, and a permission the matrix shows and no endpoint consults
        is a row that means nothing.

        The waiver is gated on `approvals:decide` rather than on `org:settings`
        because of what it is: raising the ceiling on standing consent is a
        decision about the approval queue, and somebody who may not decide one
        approval should not be able to switch the queue off for every
        conversation (#925).

        The speech-to-text default falls under `org:settings` with the metadata,
        and is validated only when one of its fields is named - so a rename never
        trips over a default that went stale (#1797). Calls and dictation are
        switched on per agent, so nothing else about voice is the organization's.

        `key_scopes` are those of the API key the request came with, `None` for
        a session: each field's permission must be one the key was issued for
        too, or a key narrowed to `org:settings` reaches the budget and the
        waiver through its issuer's whole role.
        """
        org, membership = await self.get_for_user(org_id, requester_id)

        def holds(perm: Perm) -> bool:
            return role_has(membership.role, perm) and (key_scopes is None or perm in key_scopes)

        wants_budget = "monthly_budget_usd" in data.model_fields_set
        wants_proactive = data.proactive_limit_usd is not None or bool(
            data.model_fields_set & _PROACTIVE_FIELDS
        )
        wants_color = "avatar_color" in data.model_fields_set
        wants_waiver = "chat_may_waive_approvals" in data.model_fields_set
        wants_metadata = bool(
            data.model_fields_set
            - {"monthly_budget_usd", "proactive_limit_usd", "chat_may_waive_approvals"}
            - _PROACTIVE_FIELDS
        )
        if wants_metadata and not holds(Perm.ORG_SETTINGS):
            raise AuthorizationError(message="Only Owner or Admin can update the organization")
        if (wants_budget or wants_proactive) and not holds(Perm.BUDGETS_MANAGE):
            raise AuthorizationError(message="Changing a spending limit requires 'budgets:manage'")
        if wants_waiver and not holds(Perm.APPROVALS_DECIDE):
            raise AuthorizationError(
                message="Changing whether chats may waive approvals requires 'approvals:decide'"
            )

        if wants_budget:
            # Keyed on the field being named, not on its value: an explicit
            # `null` lifts the ceiling, and every other PATCH must leave it
            # exactly where it was.
            org = await organization_repo.set_monthly_budget(
                self.db, org, limit_usd=data.monthly_budget_usd
            )

        if data.proactive_limit_usd is not None:
            org = await organization_repo.set_proactive_limit(
                self.db, org, limit_usd=data.proactive_limit_usd
            )

        if data.model_fields_set & _PROACTIVE_FIELDS:
            org = await self._apply_proactivity(org, data)

        if data.model_fields_set & _WELCOME_FIELDS:
            org = await organization_repo.set_welcome_dm(
                self.db,
                org,
                enabled=(
                    org.welcome_dm_enabled
                    if data.welcome_dm_enabled is None
                    else data.welcome_dm_enabled
                ),
                text=(
                    (data.welcome_dm_text or "").strip() or None
                    if "welcome_dm_text" in data.model_fields_set
                    else org.welcome_dm_text
                ),
            )

        if wants_color:
            # Same field-named-not-valued rule: `null` resets the colour to auto.
            org = await organization_repo.set_avatar_color(self.db, org, color=data.avatar_color)

        if wants_waiver and data.chat_may_waive_approvals is not None:
            org = await organization_repo.set_chat_approval_waiver(
                self.db, org, allowed=data.chat_may_waive_approvals
            )

        if data.model_fields_set & _SPEECH_FIELDS:
            org = await self._apply_speech_settings(org, data)

        return await organization_repo.update(
            self.db,
            org,
            name=data.name,
            avatar_url=data.avatar_url,
        )

    async def _apply_proactivity(self, org: Organization, data: OrganizationUpdate) -> Organization:
        """Merge the named proactivity fields over the stored ones, check, and write.

        The model is chosen, never defaulted (#2301): the work spends money nobody
        asked for in the moment, so turning it on without one - or clearing the
        one it runs on while it is on - is refused, naming the model field. A
        profile named must be one of this organization's.
        """
        named = data.model_fields_set
        enabled = (
            org.proactive_enabled if data.proactive_enabled is None else data.proactive_enabled
        )
        watches = (
            org.proactive_watches_enabled
            if data.proactive_watches_enabled is None
            else data.proactive_watches_enabled
        )
        profile_id = (
            data.proactive_model_profile_id
            if "proactive_model_profile_id" in named
            else org.proactive_model_profile_id
        )
        if (
            "proactive_model_profile_id" in named
            and profile_id is not None
            and await credential_repo.get_profile(self.db, profile_id, organization_id=org.id)
            is None
        ):
            raise refused_field(
                "proactive_model_profile_id", "That model is not one of this organization's"
            )
        if (enabled or watches) and profile_id is None:
            raise refused_field(
                "proactive_model_profile_id",
                "Choose the model the proactive work runs on before turning it on",
            )
        org = await organization_repo.set_proactivity(
            self.db,
            org,
            enabled=enabled,
            model_profile_id=profile_id,
            days=org.proactive_days if data.proactive_days is None else data.proactive_days,
            hour=org.proactive_hour if data.proactive_hour is None else data.proactive_hour,
            timing=org.proactive_timing if data.proactive_timing is None else data.proactive_timing,
        )
        return await organization_repo.set_watch_policy(
            self.db,
            org,
            enabled=watches,
            min_minutes=(
                org.proactive_watch_min_minutes
                if data.proactive_watch_min_minutes is None
                else data.proactive_watch_min_minutes
            ),
        )

    async def _apply_speech_settings(
        self, org: Organization, data: OrganizationUpdate
    ) -> Organization:
        """Merge the named speech fields over the stored ones, check the result, write it.

        Checked after the merge, because the rules span fields: a pair must be one
        the catalog offers, and it is sent with a key named beside it - an
        organization-visible API key for that provider
        (`SpeechToTextSettingsService.key_problem`), since the platform spends
        it for everybody. No pair here is allowed: an agent may carry its own
        (`SpeechToTextSpec`), and one that has none dictates in the browser.

        Only what the request changes is checked: the pair and its key when it
        names the provider, the model or the key. A rename never trips over a
        pair that went stale after its model was withdrawn or its key deleted. A
        refusal names a field the request sent.

        `null` clears the provider, the model, the key and the language; on the
        length, which cannot be empty, it leaves the stored value alone. Clearing the pair clears its key with it - a key left behind
        would ride along to whichever provider is chosen next.
        """
        named = data.model_fields_set
        provider = (
            data.speech_to_text_provider
            if "speech_to_text_provider" in named
            else org.speech_to_text_provider
        )
        model = (
            data.speech_to_text_model
            if "speech_to_text_model" in named
            else org.speech_to_text_model
        )
        secret_id = (
            data.speech_to_text_secret_id
            if "speech_to_text_secret_id" in named
            else org.speech_to_text_secret_id
        )
        language = (
            data.speech_to_text_language
            if "speech_to_text_language" in named
            else org.speech_to_text_language
        )
        max_seconds = data.dictation_max_seconds or org.dictation_max_seconds
        pair_field = (
            "speech_to_text_model"
            if "speech_to_text_model" in named
            else "speech_to_text_provider"
            if "speech_to_text_provider" in named
            else None
        )
        key_named = "speech_to_text_secret_id" in named
        if pair_field is not None or key_named:
            field = pair_field or "speech_to_text_secret_id"
            key_field = "speech_to_text_secret_id" if key_named else field
            if provider is None or model is None:
                if provider is not None or model is not None:
                    raise refused_field(
                        field, "Choose a provider and a model together, or clear both."
                    )
                if key_named and secret_id is not None:
                    raise refused_field(
                        key_field, "A key goes with a provider and a model - choose those first."
                    )
                secret_id = None
            elif not speech_to_text.is_offered(provider, model):
                raise refused_field(
                    field, "That provider does not offer this model for transcription."
                )
            elif secret_id is None:
                raise refused_field(key_field, f"Choose a key for {provider} to transcribe with.")
            else:
                problem = await SpeechToTextSettingsService(self.db).key_problem(
                    secret_id, organization_id=org.id, provider=provider, ctx=None
                )
                if problem is not None:
                    raise refused_field(key_field, problem)
        if (
            "speech_to_text_language" in named
            and language is not None
            and language not in speech_to_text.LANGUAGES
        ):
            raise refused_field(
                "speech_to_text_language", "Transcription does not accept that language code."
            )
        return await organization_repo.set_speech_settings(
            self.db,
            org,
            provider=provider,
            model=model,
            secret_id=secret_id,
            language=language,
            max_seconds=max_seconds,
        )

    async def delete(self, org_id: UUID, requester_id: UUID) -> None:
        """Delete org. Requires OWNER role. Personal orgs cannot be deleted."""
        org, membership = await self.get_for_user(org_id, requester_id)

        if org.is_personal:
            raise BadRequestError(message="Personal organization cannot be deleted")
        if not role_has(membership.role, Perm.ORG_DELETE):
            raise AuthorizationError(message="Only the Owner can delete the organization")

        await self.purge(org)

    async def purge(self, org: Organization) -> None:
        """Remove an organization and its org-scoped collections, no guards.

        The guards live in :meth:`delete`; this is the shared teardown, also
        reached when a user's account is deleted and their personal org goes with
        them (`app.services.user.UserService.delete`). Org-scoped collections are
        removed explicitly first: `knowledge_bases.organization_id` is
        `ON DELETE SET NULL`, and nulling an org-scoped row violates
        `ck_knowledge_bases_org_scope_has_org` (#9). Personal collections that
        merely carry this org's id are left to the `SET NULL` - but that flips
        their `vector_tenant` to `None` while their rows stay stamped with the
        deleted org, so the deferred cleanup re-stamps those rows to untagged,
        matching the `None` read scope again rather than stranding them (#1684).

        Two locks, in one order. Each doomed collection's `COLLECTION_TEARDOWN`
        lock is taken first, from a snapshot read without the row lock, and only
        then the org row `FOR UPDATE`: a claim takes the teardown lock and then the
        org FK, so a purge that took the org row first would cross it into an ABBA
        deadlock (#1387). The `FOR UPDATE` still comes before the authoritative
        list-and-delete, so an org-scoped collection inserted concurrently (it
        takes FOR KEY SHARE on this row) cannot slip between the list and the
        DELETE, be nulled by the `SET NULL`, and violate the same CHECK - a fresh
        read under READ COMMITTED (#1115). A collection created in the gap between
        the snapshot and that `FOR UPDATE` is found by the authoritative list and
        has no lock held for it, so it is taken here with `try_hold_name`: waiting
        would be the deadlock the order exists to avoid, and a name this purge
        drops without reserving is a name another organization can claim in the
        commit-to-drop window - adopting a table still holding the deleted
        organization's vectors, which the deferred cleanup then *preserves* on
        seeing the new reference. Where the lock cannot be taken, a claim for that
        very name is in flight and nothing this transaction does can make the drop
        safe, so it refuses and is retried rather than leaking (#1389).

        Each collection's document rows go before its identifiers do:
        `rag_documents` authorization keys on `collection_name`, so a row left
        behind is readable by a later collection permitted the same name (#1116).
        Deleting by `knowledge_base_id` scopes this to the KB being torn down; a
        doc row that shares the name but carries no KB link, and the vectors that
        stay in a shared table kept below, are #913 residuals this cannot reach
        without a tenant column to filter on.

        The external side effects - dropping each physical vector table and
        unlinking the stored uploads - are a cleanup job queued in the purge's own
        transaction (`queue_external_state_cleanup`). It runs only if the
        relational teardown committed, so a final commit that fails rolls back the
        org, KB and doc rows - and the job with them - and leaves none of them
        pointing at a table or a file already gone (#1137); and a process that
        dies after the commit no longer takes the cleanup with it - the job is in
        the database, and a worker retries it (#1274). A collection another organization still references is
        not dropped - `collection_name` is not tenant-unique (#913) - and each name
        that is dropped is reserved in `collection_teardowns`, committed with the
        delete, so a claim of the name in the commit-to-drop window is refused rather
        than adopting the still-populated table (#1362). The gap this does not close
        is commit-to-dispatch - a crash before `spawn_after_commit` fires still loses
        the cleanup, which only a record committed with the delete (an outbox) would
        close.
        """
        # Teardown locks before the org row lock, from a snapshot read without it,
        # so claim (teardown then org FK) and purge cannot invert into a deadlock
        # (#1387). Sorted, so two purges sharing a name (#913) take it in one order.
        held: set[str] = set()
        if self._vector_store is not None:
            snapshot = await knowledge_base_repo.list_org_scoped(self.db, org.id)
            for collection in sorted({kb.collection_name for kb in snapshot}):
                await hold_name(self.db, LockScope.COLLECTION_TEARDOWN, collection)
                held.add(collection)

        await organization_repo.get_by_id_for_update(self.db, org.id)
        collections: list[str] = []
        storage_paths: list[str] = []
        for kb in await knowledge_base_repo.list_org_scoped(self.db, org.id):
            storage_paths.extend(await rag_document_repo.delete_by_knowledge_base(self.db, kb.id))
            collections.append(kb.collection_name)
            await knowledge_base_repo.delete(self.db, kb.id)

        # A personal base carrying this org's id is left standing by the `SET NULL`,
        # which flips its `vector_tenant` to `None` while its rows stay stamped with
        # the org - stranding them behind the read side's `IS NULL` scope. Each is
        # handed to the deferred cleanup, which untags that base's own rows so they
        # match again. Identified here, under the org lock, before the `SET NULL`:
        # the cleanup re-stamps by the base's own `parent_doc_id`s (resolved at run
        # time), so it touches only its own documents even on a table it shares with
        # this org's own torn-down collection, and never another tenant's rows (#1684).
        restamp_orphans: list[KnowledgeBase] = []
        if self._vector_store is not None:
            restamp_orphans = await knowledge_base_repo.list_personal_carrying_org(self.db, org.id)

        await organization_repo.delete(self.db, org)

        # A store is wired only on the teardown path, and it is the signal to clean up
        # the vector tables. A collection another organization still references is left
        # alone - the name is not tenant-unique (#913). The rest are dropped by the
        # deferred cleanup, which re-reads the reference check under the teardown lock
        # (#1355), and every one of them is reserved, so a claim in the
        # commit-to-drop window is refused rather than adopting the still-populated
        # table (#1362). Both readings below therefore happen under the name's lock:
        # the ones the snapshot saw are already held, and one created since is taken
        # without waiting - see the note above on why waiting here cannot be done and
        # why a name that cannot be locked is a refusal rather than an unreserved drop.
        # Files are unlinked whether or not a store was wired.
        to_drop: list[str] = []
        if self._vector_store is not None:
            for collection in dict.fromkeys(collections):
                if collection not in held and not await try_hold_name(
                    self.db, LockScope.COLLECTION_TEARDOWN, collection
                ):
                    raise ConcurrentChangeError(
                        message=(
                            "This organization gained a knowledge collection while it "
                            "was being deleted, and something else is working on that "
                            "collection right now. Nothing was deleted; try again."
                        ),
                        details={"collection_name": collection},
                    )
                held.add(collection)
                if await knowledge_base_repo.list_by_collection_name(self.db, collection):
                    continue
                to_drop.append(collection)
                await collection_teardown_repo.reserve(self.db, collection)
        restamps = [
            Restamp(collection=kb.collection_name, organization_id=org.id, knowledge_base_id=kb.id)
            for kb in restamp_orphans
        ]
        # The images, speech and video its agents generated go in the same job
        # (#2310): their rows cascade with the organization, so the job is the
        # only record of the bytes left. One prefix, which also takes the files
        # written before they were recorded - and why the job is now always queued.
        from app.services.generated_media import organization_directory
        from app.worker.tasks.teardown_tasks import queue_external_state_cleanup

        await queue_external_state_cleanup(
            self.db,
            storage_paths,
            to_drop,
            restamps,
            prefixes=[organization_directory(org.id)],
            organization_id=org.id,
        )
        # Whatever the `media` capability offloaded out of any of this tenant's
        # compacted histories. Content-addressed objects record nothing about who
        # still references them, so the tenant's prefix is the outer bound of
        # their lifetime and this is where it ends (#55). Unconditional: it is
        # one directory removal, and a tenant that offloaded nothing has none.
        from app.agents.capabilities.media import organization_prefix_for
        from app.core.background import spawn_after_commit as spawn
        from app.services.file_storage import delete_prefix_best_effort

        spawn(
            self.db,
            delete_prefix_best_effort(organization_prefix_for(org.id)),
            name="org_purge_media",
        )

    async def upload_avatar(
        self,
        org_id: UUID,
        requester_id: UUID,
        file_data: bytes,
        content_type: str | None,
    ) -> Organization:
        """Replace the organization avatar. Requires ADMIN or OWNER role.

        Raises:
            BadRequestError: If file type or size is invalid.
            AuthorizationError: If requester is not Owner or Admin.
        """
        if content_type not in self._ALLOWED_AVATAR_TYPES:
            raise BadRequestError(message="Only JPEG, PNG, WebP, and GIF images are allowed")
        if len(file_data) > 2 * 1024 * 1024:
            raise BadRequestError(message="Avatar image too large. Maximum 2MB.")

        org, membership = await self.get_for_user(org_id, requester_id)
        if not role_has(membership.role, Perm.ORG_SETTINGS):
            raise AuthorizationError(message="Only Owner or Admin can update the org")

        storage = get_file_storage()
        if org.avatar_url:
            with contextlib.suppress(Exception):
                await storage.delete(org.avatar_url)
        # Stored under a suffix from the validated type, not the caller's
        # filename, so a valid image is renderable whatever it was named (#702).
        storage_path = await storage.save(
            f"avatars/orgs/{org_id}", avatar_filename(content_type), file_data
        )
        return await organization_repo.update(self.db, org, avatar_url=storage_path)
