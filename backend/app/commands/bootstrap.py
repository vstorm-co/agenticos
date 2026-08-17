"""Bring a fresh installation to a running agent.

`seed` fills the database with sample rows; this does something narrower and
more useful - it produces the shortest path from `docker compose up` to an
agent that answers a question. An empty AgenticOS is a chicken-and-egg problem:
an agent needs a model, a model needs a key, a key needs an organization. This
walks that chain once so a new operator can see the thing work before deciding
whether to learn it.

Deliberately idempotent. Running it twice is what people do when they are not
sure it worked the first time, and it should not punish them for that.
"""

from __future__ import annotations

import asyncio
import uuid

import click

from app.agents.spec import AgentSpec
from app.commands import command, info, success, warning
from app.core.config import settings
from app.core.permissions import AuthContext, OrgRoleName
from app.core.secret_kinds import ApiKeySecret
from app.db.models.resource_grant import Visibility
from app.db.session import get_db_context
from app.repositories import agent_repo, credential_repo, member_repo, organization_repo
from app.schemas.user import UserCreate
from app.services.agent_registry import AgentRegistryService, slugify
from app.services.model_profile import ModelProfileService
from app.services.organization_secret import OrganizationSecretService
from app.services.user import UserService

# The demo agent. Kept plain on purpose: someone reading it should see that an
# agent is just instructions plus a couple of capabilities, not a framework.
DEMO_AGENT_NAME = "Getting Started"
DEMO_INSTRUCTIONS = """You are a helpful assistant running on AgenticOS.

When asked what you can do, explain plainly: you were defined by configuration
rather than code, your instructions live in an agent spec, and the capabilities
you have were switched on in the Builder. Keep answers short.
"""

# Model ids for the providers bootstrap offers, so the demo agent runs without
# the operator having to look one up. Namespaced for OpenRouter, which rejects a
# bare id. This is a shortlist, not the catalog: bootstrap exists to get one
# agent answering, and every other provider is two clicks away in Settings.
DEFAULT_MODELS: dict[str, str] = {
    "openai": "gpt-4.1",
    "anthropic": "claude-sonnet-4-6",
    "google": "gemini-2.5-pro",
    "openrouter": "openai/gpt-4.1",
}


@command("bootstrap", help="Create an organization, an owner, a model and a working agent")
@click.option("--email", default="admin@example.com", help="Owner email")
@click.option("--password", default="admin123", help="Owner password")
@click.option("--org", "org_name", default="Acme", help="Organization name")
@click.option(
    "--provider",
    type=click.Choice(sorted(DEFAULT_MODELS)),
    default="openai",
    help="Which provider the demo agent runs on",
)
@click.option(
    "--api-key",
    envvar="BOOTSTRAP_API_KEY",
    default=None,
    help="Provider API key. Without it the agent is created but cannot run.",
)
@click.option("--model", "model_id", default=None, help="Model id (defaults per provider)")
def bootstrap(
    email: str,
    password: str,
    org_name: str,
    provider: str,
    api_key: str | None,
    model_id: str | None,
) -> None:
    """Walk a fresh install to a running agent."""
    asyncio.run(_bootstrap(email, password, org_name, provider, api_key, model_id))


async def _bootstrap(
    email: str,
    password: str,
    org_name: str,
    provider: str,
    api_key: str | None,
    model_id: str | None,
) -> None:
    async with get_db_context() as db:
        user_service = UserService(db)

        user = await user_service.get_by_email(email)
        if user is None:
            user = await user_service.register(
                UserCreate(email=email, password=password, full_name="Owner")
            )
            success(f"Created owner {email}")
        else:
            info(f"Owner {email} already exists")

        # The bootstrap owner administers the deployment, not just their
        # organization - /admin, bulk /rag and user management all gate on
        # this flag. Idempotent, like everything else here.
        if not user.is_app_admin:
            user.is_app_admin = True
            await db.flush()
            success(f"Granted platform admin to {email}")

        org = await _resolve_organization(db, user.id, org_name)
        ctx = AuthContext(user_id=user.id, organization_id=org.id, role=OrgRoleName.OWNER)

        profile_id = await _resolve_model(db, ctx, provider, api_key, model_id)
        await _resolve_demo_agent(db, ctx, profile_id)
        await db.commit()

    click.echo()
    success("Ready.")
    click.echo(f"  Sign in as {email}")
    if api_key is None:
        warning("  No API key given - add one under Settings → AI providers to run the agent.")
    else:
        click.echo("  Open Agents → Getting Started → Test and ask it something.")


async def _resolve_organization(db, owner_id: uuid.UUID, name: str):
    """The owner's organization, created if this is a fresh install.

    Registration already creates a personal organization; reusing it keeps the
    demo in the place a new operator will actually land after signing in.
    """
    personal = await organization_repo.get_personal_for_user(db, owner_id)
    if personal is not None:
        info(f"Using organization {personal.name}")
        return personal

    org = await organization_repo.create(
        db,
        name=name,
        slug=slugify(name),
        created_by_user_id=owner_id,
        monthly_budget_usd=settings.DEFAULT_ORG_MONTHLY_BUDGET_USD,
    )
    await member_repo.create(
        db, organization_id=org.id, user_id=owner_id, role=OrgRoleName.OWNER.value
    )
    success(f"Created organization {name}")
    return org


async def _resolve_model(
    db, ctx: AuthContext, provider: str, api_key: str | None, model_id: str | None
) -> uuid.UUID | None:
    """The default model profile bootstrap names, built from a supplied key.

    Idempotent on the profile it *names*, not on whatever the organization
    happens to hold. It used to adopt the first profile it found, so on a
    developer database that already had one - an unrelated `OpenRouter ·
    openai/gpt-5.1`, or a profile a failed spec leaked - it reused that and
    never created `openai default`. Idempotence that reuses whatever it finds is
    not idempotence: the promise of `make platform-bootstrap` is a *known*
    starting point, and that only holds if the profile it guarantees is the one
    it created. So it looks for `<provider> default`, and reuses only that.

    Nothing keyless is created. A keyless profile is a row that can never run
    and that nothing repoints: models are keyed from the vault now, and the only
    way to give one a key is to add the model again. It showed up in the Builder
    as `openai default · no key`, an option whose sole effect was to make an
    agent fail at its first message.

    Returns None when there is no key, and the caller leaves the demo agent as
    a draft rather than publishing something that cannot answer.
    """
    label = f"{provider} default"
    existing = await credential_repo.get_profile_by_label(
        db, label, organization_id=ctx.organization_id
    )
    if existing is not None:
        info(f"Using model {existing.label}")
        return existing.id

    if api_key is None:
        info(f"No {provider} key given - add one in the vault, then add a model")
        return None

    # Into the vault, like every other key. It is the same store the Vault page
    # shows and the same one a model picker reads, so a bootstrapped deployment
    # starts in the state a hand-built one ends in.
    secret = await OrganizationSecretService(db).create(
        ctx,
        name=f"{provider} (bootstrap)",
        value=ApiKeySecret(api_key=api_key),
        purpose=provider,
        visibility=Visibility.ORG,
    )
    success(f"Stored {provider} key (…{secret.hint})")

    model = model_id or DEFAULT_MODELS[provider]
    profile = await ModelProfileService(db).create_profile(
        ctx,
        label=label,
        provider=provider,
        model=model,
        secret_id=secret.id,
    )
    success(f"Created model {profile.label} ({model})")
    return profile.id


async def _resolve_demo_agent(db, ctx: AuthContext, profile_id: uuid.UUID | None) -> None:
    """An agent that answers questions about itself, published if it can run.

    Without a model there is nothing to publish: validation refuses a spec that
    names no profile when the organization has no default, and an agent that
    published anyway would answer its first message with an error. It is left as
    a draft, which is what it is - one key away from working.
    """
    slug = slugify(DEMO_AGENT_NAME)
    if await agent_repo.get_by_slug(db, slug, organization_id=ctx.organization_id):
        info(f"Agent @{slug} already exists")
        return

    service = AgentRegistryService(db)
    spec = AgentSpec(
        name=DEMO_AGENT_NAME,
        description="Explains what this platform does. Delete it once you have your own.",
        instructions=DEMO_INSTRUCTIONS,
        model_profile_id=profile_id,
        capabilities=[{"id": "clock"}],
    )
    agent = await service.create(ctx, spec)
    if profile_id is None:
        info(f"Agent @{slug} saved as a draft - add a model, then publish it")
        return
    await service.publish(ctx, agent.id, note="Bootstrap")
    success(f"Published agent @{slug}")
