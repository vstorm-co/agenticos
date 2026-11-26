"""Fresh admission and independent receipts for each paid embedding diagnostic call."""

import asyncio
from collections.abc import Awaitable, Callable
from dataclasses import replace

from pydantic_ai.usage import RequestUsage
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.capabilities.budget import (
    SpendLedger,
    metered_by,
    price_request,
    record_ambient_cost,
)
from app.core.exceptions import AuthorizationError, BadRequestError
from app.core.permissions import AuthContext
from app.db.session import get_independent_db_context
from app.repositories import ingestion_spend_repo, organization_repo
from app.services.access import decider_context, member_context
from app.services.api_key import ApiKeyService
from app.services.embedding_resolution import TargetIdentity
from app.services.rag.embeddings import EmbeddingProbeError
from app.services.spend import assert_organization_within_budget

AuthorizeProbe = Callable[[AsyncSession, AuthContext], Awaitable[None]]
ProbeRequest = Callable[[], Awaitable[list[float]]]
CALL_SETTLEMENT_SECONDS = 35
RECEIPT_SECONDS = 10


async def current_probe_context(db: AsyncSession, admitted: AuthContext) -> AuthContext:
    """Refresh the issuer without widening the credential admitted to this request."""
    if admitted.user_id is None or admitted.subject_is_publisher_fallback:
        raise AuthorizationError(
            message="A connected organization member must start this Test", details={}
        )
    if admitted.api_key_id is not None:
        current = await ApiKeyService(db).context_for_key(
            admitted.api_key_id, organization_id=admitted.organization_id
        )
        if current.user_id != admitted.user_id:
            raise AuthorizationError(
                message="The Test credential no longer belongs to its issuer", details={}
            )
        scopes = (
            current.key_scopes
            if admitted.key_scopes is None
            else admitted.key_scopes
            if current.key_scopes is None
            else admitted.key_scopes & current.key_scopes
        )
        return replace(
            admitted,
            role=current.role,
            is_app_admin=admitted.is_app_admin and current.is_app_admin,
            key_scopes=scopes,
            key_internal=admitted.key_internal or current.key_internal,
        )
    context = decider_context if admitted.is_app_admin else member_context
    current = await context(db, organization_id=admitted.organization_id, user_id=admitted.user_id)
    if current is None:
        raise AuthorizationError(
            message="Your organization membership is no longer active", details={}
        )
    return replace(
        admitted, role=current.role, is_app_admin=admitted.is_app_admin and current.is_app_admin
    )


async def run_probe_call(
    *,
    actor: AuthContext,
    identity: TargetIdentity,
    model: str,
    authorize: AuthorizeProbe,
    request: ProbeRequest,
) -> list[float]:
    """Admit a fresh call, then settle its reported spend before returning or cancelling.

    A cancelled caller does not replay the HTTP request. Its already admitted
    task is retained and bounded while it collects known usage and commits its
    receipt. Process death or a lost provider response cannot reveal unknown fees.
    """
    async with get_independent_db_context() as db:
        current = await current_probe_context(db, actor)
        await authorize(db, current)
        payer = identity.key_organization_id
        capped = False
        if payer is not None:
            await assert_organization_within_budget(db, payer)
            organization = await organization_repo.get_by_id(db, payer)
            capped = organization is not None and organization.monthly_budget_usd is not None
            if capped and price_request(RequestUsage(input_tokens=1), model, "openai") is None:
                raise BadRequestError(
                    message="This Test cannot enforce the organization's dollar budget because the model's price is unknown. Choose a priced model or remove the dollar cap explicitly.",
                    details={"model": model},
                )
    ledger = SpendLedger()
    with metered_by(ledger):
        task = asyncio.create_task(_settled_call(request, ledger, identity, model, capped))
    cancellation: asyncio.CancelledError | None = None
    while not task.done():
        try:
            await asyncio.wait({task})
        except asyncio.CancelledError as error:
            cancellation = error
    if cancellation is not None:
        try:
            task.result()
        except Exception as failure:
            raise BaseExceptionGroup(
                "Embedding Test failed during cancellation", [cancellation, failure]
            ) from None
        raise cancellation
    return task.result()


async def _settled_call(
    request: ProbeRequest, ledger: SpendLedger, identity: TargetIdentity, model: str, capped: bool
) -> list[float]:
    outcome: list[float] | EmbeddingProbeError
    deadline = asyncio.timeout(CALL_SETTLEMENT_SECONDS)
    try:
        async with deadline:
            try:
                outcome = await request()
            except EmbeddingProbeError as error:
                outcome = error
    except TimeoutError:
        if not deadline.expired():
            raise
        if not ledger.entries:
            with metered_by(ledger):
                record_ambient_cost(model, None)
        outcome = EmbeddingProbeError("unreachable")
    finally:
        if identity.key_organization_id is not None and ledger.entries:
            async with asyncio.timeout(RECEIPT_SECONDS), get_independent_db_context() as db:
                await ingestion_spend_repo.record(
                    db,
                    organization_id=identity.key_organization_id,
                    rag_document_id=None,
                    model=model,
                    input_tokens=ledger.input_tokens,
                    output_tokens=ledger.output_tokens,
                    cost_usd=ledger.total_usd,
                    cost_is_partial=ledger.has_unpriced_models,
                )
    if capped and ledger.has_unpriced_models:
        raise BadRequestError(
            message="The endpoint did not report priceable usage, so this Test cannot enforce the dollar budget. Its known usage was retained; no further request was sent.",
            details={"model": model},
        )
    if isinstance(outcome, EmbeddingProbeError):
        raise outcome
    return outcome
