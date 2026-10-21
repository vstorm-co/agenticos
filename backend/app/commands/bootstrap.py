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

import asyncio
import uuid

import click

from app.agents.spec import AgentSpec
from app.commands import command, info, success, warning
from app.core.config import settings
from app.core.exceptions import AppException
from app.core.permissions import AuthContext, OrgRoleName
from app.core.secret_kinds import ApiKeySecret
from app.db.models.resource_grant import Visibility
from app.db.session import get_db_context
from app.repositories import (
    agent_repo,
    credential_repo,
    mcp_registry_server_repo,
    member_repo,
    organization_repo,
)
from app.schemas.user import UserCreate
from app.services import agent_templates, mcp_audit
from app.services.agent_registry import AgentRegistryService, slugify
from app.services.assistant import AssistantService
from app.services.mcp_registry import seed_entries
from app.services.model_profile import ModelProfileService
from app.services.organization_secret import OrganizationSecretService
from app.services.sandbox_connection import SandboxConnectionService
from app.services.user import UserService

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
        await _resolve_starter_agents(db, ctx, profile_id)
        await _resolve_mcp_mirror(db)
        await db.commit()

    click.echo()
    success("Ready.")
    click.echo(f"  Sign in as {email}")
    if api_key is None:
        warning("  No API key given - add one under Settings → AI providers to run the agents.")
    else:
        click.echo(
            "  Open Chat and ask Claude Code like something, or the Architect in the corner."
        )


async def _resolve_mcp_mirror(db) -> None:
    """Fill the MCP registry mirror, once, if nothing has.

    Here rather than left to whoever reads the docs: the table
    `0070_mcp_registry_servers` creates is empty, and an empty table is not
    visibly wrong - `/mcp` shows the curated hundred and looks complete. So the
    5,703 mirrored servers were reachable only by somebody who knew to run
    `agenticos cmd mcp-registry-sync`, which is a thing nobody knows.

    Deployment-wide, so it takes no organization and runs whichever tenant is
    being bootstrapped. Skipped when the table already holds rows: a re-run of
    bootstrap must not spend a few seconds rewriting five thousand rows that have
    not changed, and refreshing the mirror is the sync command's job.
    """
    if await mcp_registry_server_repo.count(db):
        info("MCP registry mirror already loaded")
    else:
        entries = list(seed_entries())
        for start in range(0, len(entries), 500):
            await mcp_registry_server_repo.upsert_many(db, entries[start : start + 500])
        success(f"Loaded {len(entries)} MCP registry servers")
    # What the release was checked against, so the console marks the servers
    # that answered and stops offering dead listings before anybody runs the
    # check here. A check this deployment already ran is kept.
    seeded = await mcp_audit.seed_snapshot(db)
    if seeded:
        success(f"Loaded {seeded} MCP catalog checks")


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


async def _resolve_starter_agents(db, ctx: AuthContext, profile_id: uuid.UUID | None) -> None:
    """The two agents a new organization opens with: the Architect and Claude Code like.

    The Architect is the organization's assistant, installed the way a member's
    first look installs it and published on the first model there is. Claude
    Code like comes from its template, visible to the whole organization, and is
    published on the bootstrapped model when its spec allows - a deployment with
    no sandbox to give it leaves it a draft and says why, rather than stopping.
    Idempotent: a second run finds both.
    """
    # First, whatever else happens: a deployment that runs `sandboxd` beside the API
    # has the organization's default sandbox from the moment it is bootstrapped,
    # so the starter's container workspace - and any agent made later - finds one
    # without anybody registering it (a no-op where there is no sandbox service).
    await SandboxConnectionService(db).ensure_local_connection(ctx.organization_id)
    assistant = await AssistantService(db).state(ctx)
    if assistant.status == "ready":
        success(f"Installed and published the {assistant.name}")
    else:
        info(f"The {assistant.name} is installed - it publishes once there is a model")

    template = agent_templates.get(agent_templates.STARTER_TEMPLATE)
    if template is None:  # pragma: no cover - the template ships with the image
        warning(
            f"Template {agent_templates.STARTER_TEMPLATE} is missing; no starter agent installed"
        )
        return
    slug = slugify(template.name)
    if await agent_repo.get_by_slug(db, slug, organization_id=ctx.organization_id):
        info(f"Agent @{slug} already exists")
        return
    registry = AgentRegistryService(db)
    installed = await registry.install_template(
        ctx, agent_templates.STARTER_TEMPLATE, visibility=Visibility.ORG
    )
    if profile_id is None:
        info(f"Agent @{slug} saved as a draft - add a model, then publish it")
        return
    agent = await registry.get(ctx, installed.agent_id)
    spec = AgentSpec.model_validate(agent.draft_spec).model_copy(
        update={"model_profile_id": profile_id}
    )
    await registry.save_draft(ctx, agent.id, spec)
    try:
        await registry.publish(ctx, agent.id, note="Bootstrap")
    except AppException as exc:
        warning(f"Agent @{slug} left as a draft: {exc.message}")
        return
    success(f"Published agent @{slug}")
