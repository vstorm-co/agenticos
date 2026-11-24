"""Typed decision steps using a native decision model profile.

Profiles select the provider, model, vault credential and endpoint. Existing
TypeSafe key configurations retain their model and credential behavior.
Below min_confidence the step follows its unsure port rather than treating
uncertainty as a provider failure.
"""

import asyncio
import logging
from collections.abc import Callable
from decimal import Decimal
from typing import Any, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator
from pydantic_ai import Agent, StructuredDict
from pydantic_ai.models import Model
from pydantic_ai.settings import ModelSettings
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities.budget import (
    BudgetExceeded,
    BudgetGuard,
    SpendLedger,
)
from app.agents.capabilities.guardrails import GuardrailBlocked
from app.agents.model_resolver import ModelRequestSpec, is_decision_api
from app.core.exceptions import AppException
from app.core.permissions import AuthContext, Perm
from app.core.secret_kinds import ApiKeySecret, SecretKind, unseal_kind
from app.core.vault import VaultScope
from app.db.models.organization_secret import OrganizationSecret
from app.db.session import get_worker_db_context
from app.repositories import organization_secret_repo
from app.services.access import SECRET, resolve_access
from app.services.agent_registry import AgentRegistryService
from app.services.decision_models import DEFAULT_DECISION_MODEL, decision_model_schema
from app.services.model_profile import ModelProfileService
from app.services.spend import assert_organization_within_budget
from app.services.workflow_execution import budget, context
from app.services.workflow_execution.agent_conversations import ChatSourceGuard
from app.services.workflow_execution.errors import workflow_error
from app.workflows.contracts.results import Failed, WorkflowError

logger = logging.getLogger(__name__)

KEY_PURPOSE = "typesafe"
"""The vault purpose a decision step's key is stored under - the browser's too."""

UNSURE_PORT = "unsure"

MAX_TEXT = 100_000
"""The most text one decision judges; Jev reads the whole of it in one request."""


class DecisionConfig(BaseModel):
    """The question, the model that answers it, and how sure it must be."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    question: str = Field(
        min_length=1,
        max_length=2000,
        description="What is decided about the text, asked the way a person would ask it",
    )
    model_profile_id: UUID | None = Field(
        default=None,
        title="Decision model",
        description="A native decision model profile. Existing TypeSafe-key configurations remain supported.",
        json_schema_extra={"x-resource": "model_profile", "x-model-purpose": "decision"},
    )
    secret_id: UUID | None = Field(
        default=None,
        title="Legacy TypeSafe key",
        description="A TypeSafe API key from the vault",
        json_schema_extra={"x-resource": "secret", "x-secret-kind": "api_key"},
    )
    model: str = Field(
        default=DEFAULT_DECISION_MODEL,
        min_length=1,
        max_length=64,
        description="Which Jev answers: the moving release, the preview, or a pinned version",
        json_schema_extra=decision_model_schema(),
    )
    min_confidence: float = Field(
        default=0.6,
        title="Minimum confidence (%)",
        json_schema_extra={"x-percent": True},
        ge=0,
        le=1,
        description="Below this the step goes down its unsure port instead of acting on the answer",
    )

    @model_validator(mode="after")
    def one_model_source(self) -> Self:
        if (self.secret_id is None) == (self.model_profile_id is None):
            raise ValueError("Choose a decision model profile or a legacy TypeSafe key, not both")
        return self


class DecisionInput(BaseModel):
    """The text the question is about."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    text: str = Field(min_length=1, max_length=MAX_TEXT)


class Answered(BaseModel):
    """What Jev answered, how sure it was, and how the rest of its answer was spread."""

    model_config = ConfigDict(frozen=True)

    answer: Any
    confidence: float
    probabilities: dict[str, float] = Field(default_factory=dict)
    score: float | None = None


type ModelFactory = Callable[[str, str], Model]
"""Builds the model that answers: a model name and the key. Replaced in a test."""


def typesafe_model(model_name: str, api_key: str) -> Model:  # pragma: no cover - optional extra
    """The real Jev, reached only when a decision step runs.

    Imported here so provider construction happens only when a decision runs.
    """
    from pydantic_ai.models.typesafe import TypeSafeModel
    from pydantic_ai.providers.typesafe import TypeSafeProvider

    return TypeSafeModel(model_name, provider=TypeSafeProvider(api_key=api_key))


model_factory: ModelFactory = typesafe_model


def failed(code: str, message: str, **details: Any) -> Failed:
    return Failed(error=WorkflowError(code=code, message=message, details=details))


async def _usable_key(
    db: AsyncSession, auth: AuthContext, secret_id: UUID
) -> OrganizationSecret | None:
    row = await organization_secret_repo.get(db, secret_id, organization_id=auth.organization_id)
    if (
        row is None
        or row.kind != SecretKind.API_KEY.value
        or row.purpose != KEY_PURPOSE
        or not await resolve_access(db, auth, row, Perm.SECRETS_VIEW, resource_type=SECRET)
    ):
        return None
    return row


async def check_key(db: AsyncSession, ctx: AuthContext, config: BaseModel) -> list[tuple[str, str]]:
    """Refuse a key the graph's author may not use, or one that is not TypeSafe's."""
    if not isinstance(config, DecisionConfig):
        return []
    if config.model_profile_id is not None:
        problems = await AgentRegistryService(db).model_profile_problems(
            ctx, config.model_profile_id, decision=True
        )
        if problems:
            return [("model_profile_id", problem) for problem in problems]
        profile = await ModelProfileService(db).profile_for_organization(
            ctx.organization_id, profile_id=config.model_profile_id
        )
        return (
            []
            if is_decision_api(profile.provider, profile.api)
            else [("model_profile_id", "Select a native decision API profile")]
        )
    assert config.secret_id is not None
    if await _usable_key(db, ctx, config.secret_id):
        return []
    return [("secret_id", "This is not a TypeSafe API key you can use - add one in the vault")]


def answer_schema(question: str, answer: dict[str, Any]) -> dict[str, Any]:
    """An output of one field, `answer`, whose description is the question Jev is asked."""
    return {
        "type": "object",
        "properties": {"answer": {**answer, "description": question}},
        "required": ["answer"],
        "additionalProperties": False,
    }


async def decide(config: DecisionConfig, text: str, answer: dict[str, Any]) -> Answered | Failed:
    """Ask the chosen decision model; legacy TypeSafe bindings retain their exact model."""
    current = context.current()
    resolved: ModelRequestSpec | None = None
    row: OrganizationSecret | None = None
    try:
        async with get_worker_db_context() as db:
            await ChatSourceGuard(db, current.chat_source).check()
            if config.model_profile_id is not None:
                service = ModelProfileService(db)
                profile = await service.profile_for_organization(
                    current.organization_id, profile_id=config.model_profile_id
                )
                if not is_decision_api(profile.provider, profile.api):
                    return failed(
                        "DECISION_MODEL_REQUIRED", "This step needs a native decision API profile"
                    )
                resolved = await service.resolve(
                    current.auth, profile_id=config.model_profile_id, decision=True
                )
            else:
                assert config.secret_id is not None
                row = await _usable_key(db, current.auth, config.secret_id)
            await assert_organization_within_budget(db, current.organization_id)
            limits = await budget.provider_limits(
                db, organization_id=current.organization_id, remaining=current.budget_remaining
            )
    except GuardrailBlocked as exc:
        return Failed(
            error=WorkflowError(code="AGENT_GUARDRAIL_BLOCKED", message=str(exc), bypassable=False)
        )
    except BudgetExceeded:
        return Failed(
            error=WorkflowError(
                code="BUDGET_EXCEEDED",
                message="The organization's monthly budget is exhausted",
                bypassable=False,
            )
        )
    except AppException as exc:
        return Failed(error=workflow_error(exc))
    if row is None and resolved is None:
        return failed(
            "SECRET_NOT_USABLE", "The TypeSafe key this step uses is gone or no longer usable"
        )
    provider = resolved.provider if resolved is not None else "typesafe"
    model_name = resolved.model if resolved is not None else config.model
    try:
        if resolved is not None:
            model = resolved.build()
        else:
            assert row is not None
            key = unseal_kind(
                row.sealed_secret,
                model=ApiKeySecret,
                scope=VaultScope.organization(current.organization_id),
                key_version=row.key_version,
            )
            model = model_factory(config.model, key.api_key.get_secret_value())
    except ImportError:
        return failed(
            "DECISION_MODEL_UNAVAILABLE",
            "The TypeSafe decision client is unavailable - reinstall the deployment dependencies",
        )
    ledger = SpendLedger()
    guard = BudgetGuard(
        ledger=ledger,
        provider=provider,
        limits=limits,
    )
    agent = Agent(
        model,
        output_type=StructuredDict(answer_schema(config.question, answer)),
        capabilities=[guard],
        model_settings=ModelSettings(**resolved.params) if resolved is not None else None,
    )
    try:
        async with get_worker_db_context() as db:
            await ChatSourceGuard(db, current.chat_source).check()
        result = await agent.run(text)
    except GuardrailBlocked as exc:
        return Failed(
            error=WorkflowError(code="AGENT_GUARDRAIL_BLOCKED", message=str(exc), bypassable=False)
        )
    except BudgetExceeded:
        return Failed(
            error=WorkflowError(
                code="BUDGET_EXCEEDED",
                message="This workflow has no budget left for a decision",
                bypassable=False,
            )
        )
    except asyncio.CancelledError:
        context.report_cost(Decimal(0), partial=True)
        raise
    except Exception as exc:
        # An interrupted request can have incurred spend without returning usage.
        context.report_cost(Decimal(0), partial=True)
        # A vendor's error text can carry the request, and the request is the text.
        logger.warning(
            "workflow_decision_failed",
            extra={"model": model_name, "error_type": type(exc).__name__},
        )
        return Failed(
            error=WorkflowError(
                code="DECISION_FAILED",
                message="The decision model did not answer",
                details={"model": model_name},
                retryable=True,
            )
        )
    finally:
        context.report_cost(ledger.total_usd, partial=ledger.has_unpriced_models)
    details = result.response.provider_details or {}
    return Answered(
        answer=result.output.get("answer"),
        confidence=float(_field(details, "confidence", 0.0)),
        probabilities={
            str(option): float(value)
            for option, value in _field(details, "probabilities", {}).items()
        },
        score=_field(details, "scores", None),
    )


def _field(details: dict[str, Any], key: str, default: Any) -> Any:
    """The `answer` field's entry in one of `provider_details`' per-field maps."""
    entries = details.get(key)
    return entries.get("answer", default) if isinstance(entries, dict) else default


def unsure_or(port: str, output: dict[str, Any] | None) -> frozenset[str]:
    """`unsure` for an answer below its step's confidence floor, else `port`."""
    if output is None:
        return frozenset()
    return frozenset({UNSURE_PORT if output.get("unsure") else port})
