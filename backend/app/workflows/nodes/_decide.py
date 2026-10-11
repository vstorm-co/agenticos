"""What the three decision steps share: one typed question to TypeSafe's Jev.

Jev does not write text. It answers a typed question about a text - yes or no,
pick one of these, score against these levels - with a confidence, in one
request. So a decision that an agent would spend a prompt, a generation and a
parse on is one call here, and the answer can only be one of the answers the
step allows: a choice outside the options is not something Jev can return.

Each step asks through Pydantic AI's `TypeSafeModel`, with the question as the
description of one field of a `StructuredDict` output, which is how that model
turns a schema into a question. The key is a TypeSafe **API key** from the
vault, read afresh on every run against the run's principal, so a key deleted
or unshared since publishing stops being used.

**Unsure is an answer, not a failure.** Below the step's `min_confidence` it
continues down its `unsure` port instead of acting on a coin flip, and a
workflow decides there what a person, an agent or a default does with it.
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field
from pydantic_ai import Agent, StructuredDict
from pydantic_ai.models import Model
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import AuthContext, Perm
from app.core.secret_kinds import ApiKeySecret, SecretKind, unseal_kind
from app.core.vault import VaultScope
from app.db.models.organization_secret import OrganizationSecret
from app.db.session import get_worker_db_context
from app.repositories import organization_secret_repo
from app.services.access import SECRET, resolve_access
from app.services.decision_models import DEFAULT_DECISION_MODEL, decision_model_schema
from app.services.workflow_execution import context
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
    secret_id: UUID = Field(
        title="TypeSafe key",
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
        ge=0,
        le=1,
        description="Below this the step goes down its unsure port instead of acting on the answer",
    )


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

    Imported here because `typesafe-sdk` ships with the `browser` extra; a
    deployment without it is told so by :func:`decide`, in a sentence.
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
    if not isinstance(config, DecisionConfig) or await _usable_key(db, ctx, config.secret_id):
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
    """Ask Jev `config.question` about `text`, answered in the shape `answer` describes."""
    current = context.current()
    async with get_worker_db_context() as db:
        row = await _usable_key(db, current.auth, config.secret_id)
    if row is None:
        return failed(
            "SECRET_NOT_USABLE", "The TypeSafe key this step uses is gone or no longer usable"
        )
    key = unseal_kind(
        row.sealed_secret,
        model=ApiKeySecret,
        scope=VaultScope.organization(current.organization_id),
        key_version=row.key_version,
    )
    try:
        model = model_factory(config.model, key.api_key.get_secret_value())
    except ImportError:
        return failed(
            "DECISION_MODEL_UNAVAILABLE",
            "This deployment was built without TypeSafe - install the 'browser' extra",
        )
    agent = Agent(model, output_type=StructuredDict(answer_schema(config.question, answer)))
    try:
        result = await agent.run(text)
    except Exception:
        # A vendor's error text can carry the request, and the request is the text.
        logger.exception("workflow_decision_failed", extra={"model": config.model})
        return Failed(
            error=WorkflowError(
                code="DECISION_FAILED",
                message="The decision model did not answer",
                details={"model": config.model},
                retryable=True,
            )
        )
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
