import logging
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities.subagents import SubagentsConfig
from app.agents.spec import AgentSpec, SubagentRef
from app.core.exceptions import AuthorizationError, BadRequestError, NotFoundError
from app.core.permissions import AuthContext
from app.db.models.agent import Agent, AgentVersion, Visibility
from app.repositories import agent_repo, conversation_repo, credential_repo, user_repo
from app.schemas.onboarding import (
    CreatedAgentInfo,
    CreateOnboardingTeamRequest,
    OnboardingProfileRequest,
    OnboardingTeamProposal,
    OnboardingTeamResult,
    ProposedLead,
    ProposedSpecialist,
)
from app.services import agent_templates
from app.services.agent_registry import AgentRegistryService, slugify
from app.services.model_profile import usable_for_agents
from app.services.primary_conversation import PrimaryConversationService

logger = logging.getLogger(__name__)

# Industry-specific proposals and starters
_INDUSTRY_DEFAULTS: dict[str, dict[str, str]] = {
    "software": {
        "lead_name": "Tech Lead & Orchestrator",
        "lead_role": "Engineering Lead",
        "lead_desc": "Coordinates engineering workflows, dispatches tasks to specialists, and synthesizes answers across codebase, releases, and support.",
        "starter_1": "What changes are ready to be included in our release notes?",
        "starter_2": "How should external developers integrate with our API endpoints?",
        "starter_3": "Help triage an incoming alert or error incident",
        "rationale": "Engineers and technical teams spend hours on docs, releases, and incident response. This team pairs an orchestrator with specialized support and repo agents to keep development velocity high.",
    },
    "ecommerce": {
        "lead_name": "Store Operations Lead",
        "lead_role": "E-Commerce Coordinator",
        "lead_desc": "Orchestrates online store operations, monitors supplier inventory, resolves order inquiries, and writes compelling listings.",
        "starter_1": "Where is order #1042 and what is its fulfillment status?",
        "starter_2": "Draft high-converting product copy and bullet points for our new item",
        "starter_3": "Check our current stock cover and highlight any supplier risks",
        "rationale": "E-commerce moves fast across catalog management, inventory tracking, and order fulfillment. This team gives you dedicated agents for listings, operations, and support.",
    },
    "finance": {
        "lead_name": "Finance Operations Lead",
        "lead_role": "Finance Coordinator",
        "lead_desc": "Supervises reporting workflows, clarifies policy terms, checks compliance packs, and assists month-end close.",
        "starter_1": "What are our terms and timelines for customer refunds or fees?",
        "starter_2": "Review our month-end close readiness and flag blocking items",
        "starter_3": "Check this onboarding document pack for completeness and consistency",
        "rationale": "Financial operations demand precision and compliance. This specialist team automates policy Q&A, checklist auditing, and close management with audit-ready accuracy.",
    },
    "healthcare": {
        "lead_name": "Clinic Operations Lead",
        "lead_role": "Practice Coordinator",
        "lead_desc": "Coordinates administrative workflows, clinical procedure guidance, patient discharge notes, and incident tracking.",
        "starter_1": "Draft a clinical discharge summary for patient review",
        "starter_2": "What is our standard protocol for appointment check-in?",
        "starter_3": "Log and summarize an operational or quality incident factually",
        "rationale": "Healthcare and clinical practices must balance patient communication with strict procedural compliance. This team handles administrative load so staff can focus on care.",
    },
    "legal": {
        "lead_name": "Legal Practice Lead",
        "lead_role": "Legal Coordinator",
        "lead_desc": "Coordinates matter intakes, contract reviews, case law research, and client status reports.",
        "starter_1": "Review this agreement draft and highlight liability or indemnification terms",
        "starter_2": "Draft a clear matter status update for our client",
        "starter_3": "Research jurisdictional precedents and citing authorities on this question",
        "rationale": "Legal teams manage heavy document volume and repetitive drafting. This team accelerates first-pass contract analysis and research without sacrificing diligence.",
    },
    "manufacturing": {
        "lead_name": "Production Operations Lead",
        "lead_role": "Plant Operations Coordinator",
        "lead_desc": "Oversees shift reporting, safety protocols, line troubleshooting, and schedule change impact analysis.",
        "starter_1": "What schedule change can line 2 absorb this week without delay?",
        "starter_2": "Diagnose this machine fault and find the documented maintenance procedure",
        "starter_3": "Prepare the safety and shift handover briefing notes",
        "rationale": "Manufacturing operations require rapid issue containment and clear shift continuity. This team assists with scheduling, maintenance diagnostics, and quality tracking.",
    },
    "public-sector": {
        "lead_name": "Public Services Coordinator",
        "lead_role": "Public Operations Lead",
        "lead_desc": "Coordinates citizen enquiry responses, grant application checks, service outage notices, and meeting records.",
        "starter_1": "Draft a citizen response for this procedural query from published guidelines",
        "starter_2": "Check this grant application against published evaluation criteria",
        "starter_3": "Draft a clear public service disruption notice",
        "rationale": "Public sector teams require accessible, compliant citizen communication and thorough documentation. This team assists with grant checks, notices, and procedural inquiries.",
    },
    "general": {
        "lead_name": "Team Chief of Staff",
        "lead_role": "Executive Coordinator",
        "lead_desc": "Coordinates multi-disciplinary tasks, delegates to specialized agents, drafts high-impact communications, and researches questions.",
        "starter_1": "Summarize our current priorities and suggest immediate next steps",
        "starter_2": "Research best practices and write a comprehensive project brief",
        "starter_3": "Draft a company-wide update on our latest milestones",
        "rationale": "A multi-agent team led by an orchestrator lets you tackle research, content, and operations in parallel, giving every team member a high-leverage AI teammate.",
    },
}


class OnboardingTeamService:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db
        self.registry = AgentRegistryService(db)

    def propose_team(self, profile: OnboardingProfileRequest) -> OnboardingTeamProposal:
        """Generate a tailored team proposal based on industry, role, and goals."""
        ind_key = profile.industry.lower().strip()
        if ind_key not in _INDUSTRY_DEFAULTS:
            ind_key = "general"

        defaults = _INDUSTRY_DEFAULTS[ind_key]
        lead = ProposedLead(
            name=defaults["lead_name"],
            role=defaults["lead_role"],
            description=defaults["lead_desc"],
            starters=[
                defaults["starter_1"],
                defaults["starter_2"],
                defaults["starter_3"],
            ],
        )

        catalog_templates = [
            t for ind in agent_templates.catalog() if ind.id == ind_key for t in ind.templates
        ]

        specialists: list[ProposedSpecialist] = []
        if catalog_templates:
            for t in catalog_templates[:4]:
                specialists.append(
                    ProposedSpecialist(
                        key=t.key,
                        name=t.name,
                        role=t.name,
                        description=t.description,
                        capabilities=[
                            b["id"] for b in t.capabilities if isinstance(b, dict) and "id" in b
                        ],
                        recommended=True,
                    )
                )

        if not specialists or ind_key == "general":
            # Include general/agenticos and general/platform-assistant
            agenticos_tpl = agent_templates.get("general/agenticos")
            architect_tpl = agent_templates.get("general/platform-assistant")
            if agenticos_tpl:
                specialists.append(
                    ProposedSpecialist(
                        key="general/agenticos",
                        name="General Assistant",
                        role="Research & Tasks",
                        description=agenticos_tpl.description,
                        capabilities=["web_research", "artifacts", "visuals"],
                        recommended=True,
                    )
                )
            if architect_tpl:
                specialists.append(
                    ProposedSpecialist(
                        key="general/platform-assistant",
                        name="Platform Architect",
                        role="Agent & Workflow Builder",
                        description=architect_tpl.description,
                        capabilities=["skills", "visuals", "artifacts"],
                        recommended=True,
                    )
                )
            specialists.append(
                ProposedSpecialist(
                    key=None,
                    name="Research & Intelligence",
                    role="Deep Research",
                    description="Answers questions with sourced web research, citations, and structured findings.",
                    capabilities=["web_research", "web_fetch", "artifacts"],
                    recommended=True,
                )
            )

        return OnboardingTeamProposal(
            industry=ind_key,
            role=profile.role,
            rationale=defaults["rationale"],
            lead=lead,
            specialists=specialists,
        )

    async def build_team(
        self, ctx: AuthContext, request: CreateOnboardingTeamRequest
    ) -> OnboardingTeamResult:
        """Construct the team: specialists, lead with subagents delegation, and primary chat."""
        if ctx.user_id is None:
            raise AuthorizationError(message="Sign in to create an onboarding team")
        user = await user_repo.get_by_id(self.db, ctx.user_id)
        if user is None:
            raise NotFoundError(message="User not found")

        # 1. Ceiling check
        ceiling = await self.registry.ceiling(ctx)
        needed = len(request.specialists) + 1
        if ceiling.at_limit or (
            ceiling.limit is not None
            and ceiling.held is not None
            and ceiling.held + needed > ceiling.limit
        ):
            raise BadRequestError(
                message=f"Creating {needed} agents would exceed the organization limit of {ceiling.limit}."
            )

        # 2. Check available model profiles in organization
        profiles = await credential_repo.list_profiles(self.db, organization_id=ctx.organization_id)
        usable_profile_id: UUID | None = None
        for p in profiles:
            if usable_for_agents(p) and not await self.registry.model_profile_problems(ctx, p.id):
                usable_profile_id = p.id
                break

        # 3. Create / install specialists
        created_specialists: list[tuple[Agent, AgentVersion | None]] = []
        created_info: list[CreatedAgentInfo] = []

        for s in request.specialists:
            agent = None
            if s.key and agent_templates.get(s.key) is not None:
                try:
                    result = await self.registry.install_template(
                        ctx, s.key, visibility=Visibility.ORG
                    )
                    agent = await self.registry.get(ctx, result.agent_id)
                except Exception:
                    logger.warning("Could not install template %s; creating custom agent", s.key)

            if agent is None:
                agent = await self._create_custom_specialist(ctx, s, usable_profile_id)

            version = None
            if usable_profile_id is not None:
                try:
                    spec = AgentSpec.model_validate(agent.draft_spec)
                    if spec.model_profile_id is None:
                        spec = spec.model_copy(update={"model_profile_id": usable_profile_id})
                        agent = await self.registry.save_draft(ctx, agent.id, spec)
                    version = await self.registry.publish(
                        ctx, agent.id, note="Initial publication during onboarding"
                    )
                except Exception as exc:
                    logger.info("Could not auto-publish specialist %s: %s", agent.slug, exc)

            created_specialists.append((agent, version))
            created_info.append(
                CreatedAgentInfo(
                    id=agent.id,
                    name=agent.name,
                    slug=agent.slug,
                    role=s.role,
                    is_lead=False,
                    status="published" if version is not None else "draft",
                )
            )

        # 4. Build Lead Agent with subagent delegation
        subagents_pins = [
            SubagentRef(agent_id=ag.id, agent_version_id=ver.id)
            for ag, ver in created_specialists
            if ver is not None
        ]

        specialist_bullet_instructions = "\n".join(
            f'- {ag.name}: {ag.description} (delegate using `task(description=..., subagent_type="{ag.slug}")`)'
            for ag, _ in created_specialists
        )

        lead_instructions = (
            f"You are {request.lead.name}, the lead orchestrator for your team.\n\n"
            f"{request.lead.description}\n\n"
            "Your specialist team members:\n"
            f"{specialist_bullet_instructions}\n\n"
            "Guidelines:\n"
            "1. When the user's request fits a specialist's domain, delegate to them using `task(...)` and summarize the results.\n"
            "2. If a request spans multiple areas, break it down, dispatch sub-tasks to specialists, and synthesize the findings into a unified, actionable response.\n"
            "3. For general questions, explanations, or high-level coordination, answer directly.\n"
            "4. Always present your final response clearly with headings, key takeaways, and proposed next actions."
        )

        # Build capabilities for the Lead
        starter_caps = list(agent_templates.starter_capabilities().values())
        # Replace or add subagents
        lead_caps = [c for c in starter_caps if c.get("id") != "subagents"]
        lead_caps.append(
            {
                "id": "subagents",
                "config": SubagentsConfig(
                    mode="auto",
                    allow_questions=True,
                    allow_dynamic=False,
                    max_depth=2,
                    max_fanout=4,
                ).model_dump(mode="json"),
            }
        )

        unique_lead_name = await self._unique_name(ctx, request.lead.name)
        lead_spec = AgentSpec(
            name=unique_lead_name,
            description=request.lead.description,
            instructions=lead_instructions,
            capabilities=agent_templates.for_this_deployment(tuple(lead_caps)),
            subagents=subagents_pins,
            model_profile_id=usable_profile_id,
            starters=request.lead.starters,
        )

        lead_agent = await self.registry.create(ctx, lead_spec, visibility=Visibility.ORG)
        lead_status = "draft"
        if usable_profile_id is not None:
            try:
                await self.registry.publish(ctx, lead_agent.id, note="Published during onboarding")
                lead_status = "published"
            except Exception as exc:
                logger.info("Could not auto-publish lead agent %s: %s", lead_agent.slug, exc)

        created_info.insert(
            0,
            CreatedAgentInfo(
                id=lead_agent.id,
                name=lead_agent.name,
                slug=lead_agent.slug,
                role=request.lead.role,
                is_lead=True,
                status=lead_status,
            ),
        )

        # 5. Open primary conversation with Lead Agent
        conv_svc = PrimaryConversationService(self.db)
        conversation_id = await conv_svc.ensure(
            organization_id=ctx.organization_id,
            user_id=ctx.user_id,
            agent_id=lead_agent.id,
            title=lead_agent.name,
        )

        # 6. Post welcoming intro into the conversation
        bullets = "\n".join(
            f"- **{ag.name}** ({ag.slug}): {ag.description}" for ag, _ in created_specialists
        )
        welcome_message = (
            f"👋 Welcome to your new team! I am **{lead_agent.name}**, your team coordinator.\n\n"
            f"Here are the specialists on our team ready to assist you:\n"
            f"{bullets}\n\n"
            "Feel free to ask me anything or pick one of the suggestions below. I will coordinate tasks with your specialists and synthesize the results for you!"
        )
        await conversation_repo.create_message(
            self.db,
            conversation_id=conversation_id,
            role="assistant",
            content=welcome_message,
            agent_id=lead_agent.id,
        )

        # 7. Mark onboarding completed
        await user_repo.update(
            self.db,
            db_user=user,
            update_data={"onboarding_completed_at": datetime.now(UTC)},
        )
        await self.db.flush()

        return OnboardingTeamResult(
            lead_agent_id=lead_agent.id,
            lead_agent_slug=lead_agent.slug,
            lead_conversation_id=conversation_id,
            created_agents=created_info,
            message="Your team has been assembled and configured successfully.",
        )

    async def _create_custom_specialist(
        self, ctx: AuthContext, s: ProposedSpecialist, model_profile_id: UUID | None
    ) -> Agent:
        """Create a custom specialist agent from proposed spec."""
        unique_name = await self._unique_name(ctx, s.name)
        starter_caps = list(agent_templates.starter_capabilities().values())
        spec = AgentSpec(
            name=unique_name,
            description=s.description,
            instructions=(
                f"You are {unique_name}, specialist for {s.role}.\n\n"
                f"{s.description}\n\n"
                "Focus on providing accurate, clear, and actionable responses in your domain of expertise."
            ),
            capabilities=agent_templates.for_this_deployment(tuple(starter_caps)),
            model_profile_id=model_profile_id,
        )
        return await self.registry.create(ctx, spec, visibility=Visibility.ORG)

    async def _unique_name(self, ctx: AuthContext, base: str) -> str:
        """Ensure derived name produces an untaken slug within organization."""
        candidate_slug = slugify(base)
        existing = await agent_repo.get_by_slug(
            self.db, candidate_slug, organization_id=ctx.organization_id
        )
        if existing is None:
            return base

        attempt = 2
        while True:
            candidate_name = f"{base} {attempt}"
            if (
                await agent_repo.get_by_slug(
                    self.db, slugify(candidate_name), organization_id=ctx.organization_id
                )
                is None
            ):
                return candidate_name
            attempt += 1
