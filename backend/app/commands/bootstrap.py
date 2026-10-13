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
from app.repositories import (
    agent_repo,
    context_repo,
    credential_repo,
    mcp_registry_server_repo,
    member_repo,
    organization_repo,
    skill_repo,
)
from app.schemas.user import UserCreate
from app.services import skill_library
from app.services.agent_registry import AgentRegistryService, slugify
from app.services.context import ContextService
from app.services.mcp_registry import seed_entries
from app.services.model_profile import ModelProfileService
from app.services.organization_secret import OrganizationSecretService
from app.services.user import UserService

# The demo agent. Kept plain on purpose: someone reading it should see that an
# agent is just instructions plus a couple of capabilities, not a framework.
DEMO_AGENT_NAME = "Getting Started"

# The demo agent's prompt. Written here rather than borrowed: a shipped default
# is the first example of a prompt every operator reads, and half of them will
# copy it into their own agent. So it is about *judgement* - when to reach for a
# tool and when not to - rather than a list of rules, because the rules are the
# part a reader can already see in the Builder.
#
# It is deliberately not a transcription of somebody else's assistant prompt.
# Those are their authors' work, and a shipped file that quietly contains one is
# a licence problem an operator inherits without being told.
DEMO_INSTRUCTIONS = """You are the Getting Started agent on AgenticOS. You answer
questions about this platform and show what an agent here can do.

## How to answer

Answer the question that was asked, in as few words as it takes. Lead with the
answer, then the reason for it. A person asking "can it do X" wants yes or no
first.

**Answer in English**, whatever language the question arrives in. Switch only
when somebody asks you to in as many words, and then stay switched for the rest
of the conversation. Do not infer a language from the question: guessing one is
how a Polish greeting gets answered in Czech. The product's own nouns stay
English in any language - agent, spec, capability, skill, run, budget, vault,
sandbox, MCP.

Say what you do not know. If a question is about this deployment - which models
are configured, what is in a knowledge base, who has access - look it up rather
than describing how it usually works. If you cannot look it up, say so and name
what would answer it.

Never invent a number, a file name, a setting or a link. An answer with a made-up
detail in it costs more than no answer.

## When to reach for a tool

**Look before you guess.** `web_search` and `web_fetch` for anything about the
outside world that could have changed; `conversation_search` for something said
earlier in a thread you cannot see any more; `list_context` and `read_context`
for how this organization does things. Searching and being wrong is cheap;
asserting and being wrong is not.

**Plan when the work has steps.** For anything that takes more than two or three
actions, write the plan first with the planning tool and keep it current. It is
what lets a person see where you are, and what lets you resume after an
interruption.

**Delegate work that is wide rather than deep.** Independent pieces - three
sources to read, four files to check - go to sub-agents in parallel. A task that
has to be done in order stays with you. Give a delegate the whole brief: it
cannot see this conversation.

**Compute rather than estimate.** Arithmetic, dates, parsing, anything with more
than two steps: run Python. A model doing long division in its head is a model
guessing.

**Draw when a shape is the answer.** A trend, a comparison, a breakdown over
time - a chart says it in one look. A single number does not need one.

**Remember what will matter later.** Memory files are for facts that outlive this
conversation: a preference, a decision, a name. Not for a transcript.

## About this platform

You were defined by configuration rather than code. Your instructions, the
capabilities you can use, the models you run on and the budgets you run under
all live in an agent spec, published as a version somebody can read and roll
back. `AGENTS.md`, in your context, is the longer explanation - read it before
answering a question about what AgenticOS is.

When somebody asks how *you* work, show them rather than describing it: name the
capability you are about to use and why, then use it.
"""

# The context file the demo agent reads before explaining the platform. A file
# rather than more instructions, because it is the same shape a client's own
# standing knowledge takes - and because "how do I give an agent a document"
# is answered by showing one already attached.
AGENTS_MD_NAME = "AGENTS.md"
AGENTS_MD = """# AgenticOS

A self-hosted, open-source platform for a company's AI agents. It runs on your
own infrastructure, against your own model keys, and every agent in it is
configuration rather than code.

## What an agent is here

An agent is a **versioned spec**: instructions, the capabilities it may use, the
model it runs on, the budget it runs under, and what it is allowed to reach.
You configure it in the Builder, publish a version, and that frozen version is
what answers - through web chat, the HTTP API, Slack, Telegram or a widget on
your own site. Publishing mints the version; putting it in front of people is a
separate decision, so an edit cannot change what the live bot says by accident.

## What it is made of

- **Capabilities** are the unit you switch on or off: web search, running
  Python, a sandbox with files and a shell, charts, delegation to sub-agents,
  memory that outlives a conversation. They cover things that are not tools at
  all - a guardrail, a compaction strategy.
- **Knowledge collections** are documents too large to read: they are parsed,
  chunked, embedded and searched, and the agent sees only what a search returns.
- **Context files** are standing knowledge small enough to hold: a glossary, a
  policy, a brand voice. This file is one. They are injected into the prompt or
  read on demand.
- **Skills** are procedures for one kind of task, loaded when that task is what
  is happening.
- **MCP servers** connect an agent to software you already run - GitHub, Linear,
  Notion, a database - through the Model Context Protocol.

## What it is careful about

Every organization is a tenant, and nothing crosses between them. Credentials
live in a vault and never appear in a response, a log or an audit entry. Budgets
are checked before a model is called and recorded even when a call fails.
Approvals hold a tool call until a person releases it. Every run is traced, with
its cost.

## Where to look next

The Builder is where an agent is assembled. Activity is where its runs are.
The documentation site shipped with this deployment covers the rest.
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
        await _resolve_mcp_mirror(db)
        await db.commit()

    click.echo()
    success("Ready.")
    click.echo(f"  Sign in as {email}")
    if api_key is None:
        warning("  No API key given - add one under Settings → AI providers to run the agent.")
    else:
        click.echo("  Open Agents → Getting Started → Test and ask it something.")


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
        return
    entries = list(seed_entries())
    for start in range(0, len(entries), 500):
        await mcp_registry_server_repo.upsert_many(db, entries[start : start + 500])
    success(f"Loaded {len(entries)} MCP registry servers")


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


# What the demo agent can do. Everything here runs without a second credential:
# the sandbox is the in-process `state` backend rather than a container service,
# and web search defaults to DuckDuckGo. An operator who has just typed one API
# key gets an agent that can look things up, compute, draw, remember, plan and
# delegate - which is the claim this platform makes, demonstrated rather than
# described.
DEMO_CAPABILITIES: list[dict[str, object]] = [
    {"id": "clock"},
    {"id": "planning"},
    {"id": "web_research"},
    {"id": "web_fetch"},
    {"id": "code_execution"},
    {"id": "charts"},
    # `state` keeps the files in the run's own store, so there is no Docker
    # socket and no sandbox service to stand up first.
    {"id": "sandbox", "config": {"backend": "state"}},
    {"id": "context"},
    {"id": "skills"},
    {"id": "memory_files"},
    {"id": "conversation_search"},
    # Delegation with `allow_dynamic`, so it can invent a specialist for a task
    # nobody defined in advance - which is the part people do not believe until
    # they watch it happen.
    {"id": "subagents", "config": {"allow_dynamic": True}},
    {"id": "compaction"},
    {"id": "tool_output_limits"},
]


async def _resolve_agents_md(db, ctx: AuthContext) -> uuid.UUID:
    """The `AGENTS.md` this organization reads, created once.

    Idempotent like everything else here: a second run finds the file rather
    than colliding with it, and leaves whatever the operator has edited into it
    exactly as it is.
    """
    existing = await context_repo.get_by_name(
        db, AGENTS_MD_NAME, organization_id=ctx.organization_id
    )
    if existing is not None:
        return existing.id
    file = await ContextService(db).create(
        ctx,
        name=AGENTS_MD_NAME,
        description="What AgenticOS is, for an agent explaining it.",
        content=AGENTS_MD,
        visibility=Visibility.ORG,
    )
    success(f"Created context file {AGENTS_MD_NAME}")
    return file.id


async def _bundled_skill_ids(db, ctx: AuthContext) -> list[uuid.UUID]:
    """The shipped skills, bound to the demo agent.

    Creating the organization copies them in, so they are rows by the time this
    runs. Bound by name rather than assumed present: a deployment that removed
    one from the catalog gets an agent without it, not a publish that fails.
    """
    names = [entry.name for entry in skill_library.library()]
    found = [
        skill
        for name in names
        if (skill := await skill_repo.get_by_name(db, name, organization_id=ctx.organization_id))
    ]
    return [skill.id for skill in found]


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
        capabilities=DEMO_CAPABILITIES,
        context_ids=[await _resolve_agents_md(db, ctx)],
        skill_ids=await _bundled_skill_ids(db, ctx),
    )
    agent = await service.create(ctx, spec, visibility=Visibility.ORG)
    if profile_id is None:
        info(f"Agent @{slug} saved as a draft - add a model, then publish it")
        return
    await service.publish(ctx, agent.id, note="Bootstrap")
    success(f"Published agent @{slug}")
