"""The fixed-destination, interactive-only contract for personal LLM credentials."""

from app.agents.spec import AgentSpec
from app.core.exceptions import BadRequestError
from app.core.permissions import AuthContext
from app.db.models.agent_run import RunSurface

PERSONAL_MODEL_LIMITS = (
    "Personal model keys require a signed-in web chat with the configured model. "
    "Channels, widgets, hosted pages, HTTP API runs, schedules, triggers, background topics and voice "
    "are not supported. Use the organization's key for these."
)


def require_organization_model(spec: AgentSpec) -> None:
    if spec.model_credential_mode == "personal":
        raise BadRequestError(message=PERSONAL_MODEL_LIMITS, code="PERSONAL_MODEL_SURFACE")


def personal_delegate_problem(root: AgentSpec, delegate: AgentSpec) -> str | None:
    """A chat's personal-model choice authorizes that exact profile throughout its tree."""
    if delegate.model_credential_mode == "personal" and (
        root.model_credential_mode != "personal"
        or delegate.model_profile_id != root.model_profile_id
    ):
        return (
            "Personal delegates must use the personal model selected for the parent signed-in web chat. "
            "Choose the same model connection on the parent and delegate, or use organization keys."
        )
    return None


def personal_model_problems(spec: AgentSpec) -> list[str]:
    if spec.model_credential_mode != "personal":
        return []
    problems: list[str] = []
    if spec.reviewers:
        problems.append("Personal model keys do not support reviewers yet")
    if any(binding.id == "background_tasks" and binding.enabled for binding in spec.capabilities):
        problems.append("Personal model keys do not support background topics yet")
    if spec.voice is not None:
        problems.append("Personal model keys do not support voice yet")
    if any(
        binding.config.get("step_model_profile_id") or binding.config.get("model_profile_id")
        for binding in spec.capabilities
        if binding.enabled
    ):
        problems.append("Remove separate capability models before enabling personal keys")
    return problems


def require_personal_model_run(
    spec: AgentSpec,
    ctx: AuthContext,
    surface: RunSurface,
    *,
    override: object = None,
    local_model: bool = False,
    voice: bool = False,
    public_origin: bool = False,
) -> None:
    if spec.model_credential_mode != "personal":
        return
    if (
        surface != RunSurface.WEB
        or ctx.user_id is None
        or ctx.subject_is_publisher_fallback
        or ctx.api_key_id is not None
        or ctx.key_scopes is not None
        or ctx.channel_identity_id is not None
        or voice
        or local_model
        or public_origin
    ):
        raise BadRequestError(message=PERSONAL_MODEL_LIMITS, code="PERSONAL_MODEL_SURFACE")
    if override is not None and override != spec.model_profile_id:
        raise BadRequestError(
            message="This agent uses a fixed model and endpoint; clear the chat model override",
            code="PERSONAL_MODEL_OVERRIDE",
        )
    problems = personal_model_problems(spec)
    if problems:
        raise BadRequestError(message="; ".join(problems), code="PERSONAL_MODEL_CONFIGURATION")
