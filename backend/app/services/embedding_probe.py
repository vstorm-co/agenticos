"""Ask whether a change would leave a collection's stored vectors where they are.

Several edits can move a knowledge base's vector space without saying so: a new
provider, another gateway behind the same address, a model of the same width, a
rotated key that now routes elsewhere. Nothing in the settings shows it, and the
vectors already stored are only comparable with vectors from the space they were
made in. So the test asks the endpoint itself: it re-embeds a few of the base's
own stored chunks and compares the answers with what was stored.

Three chunks per base - the two shortest of at least 100 characters, and the
longest - one request each, and the base passes when the least similar pair is at
least 0.995 (cosine, both vectors normalised). One retry covers a request that
went astray. The widths have to match exactly: another width is another space, and
is reported as such rather than compared.

The person triggers it, so it is never a side effect of a save. A pass mints a
token (`embedding_probe_token`) the save presents, bound to what was tested.
Requests made here are not booked to spend: the sample is at most a few
requests per base, and the budget is checked before the first of them.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.exceptions import AuthorizationError, BadRequestError
from app.core.field_errors import refused_field
from app.core.permissions import AuthContext
from app.db.models.knowledge_base import KBScope, KnowledgeBase
from app.db.models.service_connection import ServiceConnectionKind
from app.repositories import knowledge_base_repo
from app.schemas.embedding_probe import (
    ConnectionProbeRequest,
    EmbeddingProbeEstimate,
    EmbeddingProbeResult,
    KbEmbeddingProbeRequest,
    KnowledgeBaseProbeRead,
    NewEmbeddingProbeRequest,
)
from app.schemas.knowledge_base import KnowledgeBaseUpdate
from app.services.embedding_probe_token import ProbeBinding, ProbePurpose, mint_probe_token
from app.services.embedding_resolution import (
    EmbeddingKeySource,
    EmbeddingSettings,
    EmbeddingTarget,
    TargetIdentity,
    identify_connection,
    identify_target,
    open_target,
)
from app.services.knowledge_base import KnowledgeBaseService
from app.services.rag import embedding_providers
from app.services.rag.embeddings import EmbeddingProbeError, embed_for_probe
from app.services.rag.models import StoredChunk
from app.services.rag.vectorstore import BaseVectorStore
from app.services.service_connection import KEY_PURPOSES, ServiceConnectionService
from app.services.spend import assert_organization_within_budget

PROBE_MIN_COSINE = 0.995
PROBE_MIN_CHUNK_CHARS = 100
PROBE_SHORT_CHUNKS = 2
PROBE_ATTEMPTS = 2
"""Tries per base: the first, and one retry if it did not pass."""
PROBE_WIDTH_TEXT = "AgenticOS embedding width probe."


class ProbeOutcome(StrEnum):
    PASSED = "passed"
    NO_CHUNKS = "no_chunks"
    UNREACHABLE = "unreachable"
    KEY_REFUSED = "key_refused"
    MODEL_UNKNOWN = "model_unknown"
    WRONG_WIDTH = "wrong_width"
    VECTORS_DIFFER = "vectors_differ"


_FINE = frozenset({ProbeOutcome.PASSED, ProbeOutcome.NO_CHUNKS})

_KB_FIELDS = {
    EmbeddingKeySource.PROVIDER_UNKNOWN: "embedding_provider",
    EmbeddingKeySource.NO_VAULT: "embedding_provider",
    EmbeddingKeySource.NONE_CHOSEN: "embedding_secret_id",
    EmbeddingKeySource.SECRET_MISSING: "embedding_secret_id",
    EmbeddingKeySource.SECRET_UNUSABLE: "embedding_secret_id",
    EmbeddingKeySource.SECRET_WRONG_KIND: "embedding_secret_id",
}
"""Where a degraded source is blamed on a knowledge base; the connection ones go to its endpoint."""


def min_cosine(stored: Sequence[Sequence[float]], fresh: Sequence[Sequence[float]]) -> float:
    """The lowest cosine similarity between each stored vector and its fresh pair.

    Compared after normalising both, so a model that scales its vectors differently
    is not mistaken for another space. A zero vector is similar to nothing.
    """
    return min(_cosine(old, new) for old, new in zip(stored, fresh, strict=True))


def _cosine(left: Sequence[float], right: Sequence[float]) -> float:
    norms = math.sqrt(sum(x * x for x in left)) * math.sqrt(sum(y * y for y in right))
    if norms == 0.0:
        return 0.0
    return sum(x * y for x, y in zip(left, right, strict=True)) / norms


@dataclass(frozen=True)
class _Pending:
    """One base to test, and the model to test it at."""

    kb: KnowledgeBase
    model: str


class EmbeddingProbeService:
    def __init__(self, db: AsyncSession, store: BaseVectorStore) -> None:
        self.db = db
        self.store = store
        self.bases = KnowledgeBaseService(db)
        self.connections = ServiceConnectionService(db)

    async def measure_new(
        self, ctx: AuthContext, data: NewEmbeddingProbeRequest
    ) -> EmbeddingProbeResult:
        """Embed one fixed text through a custom endpoint, to learn the width it answers at.

        A new collection has no chunks to compare, so what the test proves is that
        the endpoint answers for the model at all, and at what width - which the
        collection is then created at.

        Raises:
            AuthorizationError: For an app-scoped base by somebody who is not the
                deployment's administrator.
            BadRequestError: If the connection is not one this base may name, or
                is not an OpenAI-compatible one.
        """
        if data.scope == KBScope.APP.value and not ctx.is_app_admin:
            raise AuthorizationError(
                message="App admin required to create app-scoped knowledge base"
            )
        organization_id = None if data.scope == KBScope.APP.value else ctx.organization_id
        provider = _custom_provider()
        await self.bases._check_embedding_endpoint(
            data.embedding_endpoint_id, organization_id=organization_id, provider=provider
        )
        settings = EmbeddingSettings(
            provider=provider.provider,
            endpoint_id=data.embedding_endpoint_id,
            secret_id=None,
            base_url=None,
            model=data.embedding_model,
        )
        identity = await identify_target(self.db, settings, organization_id=organization_id)
        target = await self._usable(identity, key_field="embedding_endpoint_id", kb=True)
        await self._within_budget(identity)
        try:
            vector = await embed_for_probe(
                base_url=identity.base_url,
                api_key=target.api_key,
                keyless=target.keyless,
                model=data.embedding_model,
                text=PROBE_WIDTH_TEXT,
            )
        except EmbeddingProbeError as error:
            return _failed(ProbeOutcome(error.outcome), calls=1)
        width = len(vector)
        if not 1 <= width <= embedding_providers.MAX_MEASURED_DIM:
            return _failed(ProbeOutcome.WRONG_WIDTH, calls=1, dim=width)
        binding = ProbeBinding.of(
            ProbePurpose.KB_CREATE,
            identity,
            model=data.embedding_model,
            dim=width,
            knowledge_bases=(),
        )
        return _passed(ctx, binding, [], calls=1)

    async def estimate_kb_change(self, ctx: AuthContext, kb_id: UUID) -> EmbeddingProbeEstimate:
        kb = await self.bases.get_for_write(kb_id, ctx=ctx)
        return await self._estimate([kb])

    async def probe_kb_change(
        self, ctx: AuthContext, kb_id: UUID, data: KbEmbeddingProbeRequest
    ) -> EmbeddingProbeResult:
        """Test the settings a base would move to, with the base's own stored chunks.

        Validated exactly as the save validates them, before any request is made.
        """
        kb = await self.bases.get_for_write(kb_id, ctx=ctx)
        # Only what was named: an omitted field means keep, as `PATCH /kb/{id}` reads it.
        update = KnowledgeBaseUpdate.model_validate(
            {name: getattr(data, name) for name in data.model_fields_set}
        )
        target_settings = await self.bases.plan_embedding(kb, update, ctx=ctx)
        identity = await identify_target(
            self.db, target_settings, organization_id=kb.organization_id
        )
        target = await self._usable(identity, key_field="embedding_endpoint_id", kb=True)
        binding = ProbeBinding.of(
            ProbePurpose.KB_CHANGE,
            identity,
            model=target_settings.model,
            dim=kb.embedding_dim,
            knowledge_bases=[kb],
        )
        return await self._run(ctx, binding, target, [_Pending(kb, target_settings.model)])

    async def estimate_connection_change(
        self, ctx: AuthContext, connection_id: UUID
    ) -> EmbeddingProbeEstimate:
        row = await self.connections._editable(ctx, connection_id)
        if row.kind != ServiceConnectionKind.EMBEDDING.value:
            return EmbeddingProbeEstimate(calls=0, max_calls=0, knowledge_bases=0)
        return await self._estimate(await knowledge_base_repo.list_by_endpoint(self.db, row.id))

    async def probe_connection_change(
        self, ctx: AuthContext, connection_id: UUID, data: ConnectionProbeRequest
    ) -> EmbeddingProbeResult:
        """Test an address and key a connection would move to, against every base that uses it.

        Each base is compared in its own scope, whichever organization it belongs
        to: a deployment-wide connection is named by bases of several.
        """
        row = await self.connections._editable(ctx, connection_id)
        if row.kind != ServiceConnectionKind.EMBEDDING.value:
            return _passed_empty()
        if data.secret_id is not None:
            await self.connections._check_key(
                ctx, data.secret_id, owner=row.organization_id, provider=row.provider
            )
        if (
            row.secret_id is not None
            and row.organization_id is not None
            and data.secret_id is None
            and data.base_url not in (None, row.base_url)
        ):
            # The retained key would be sent to the new host, as a save would send
            # it: lending it takes the right to view it.
            await self.connections._viewable_key(ctx, row.secret_id, owner=row.organization_id)
        identity = await identify_connection(
            self.db,
            row,
            provider=row.provider,
            base_url=data.base_url or row.base_url,
            secret_id=data.secret_id or row.secret_id,
            requires_key=row.requires_key or data.secret_id is not None,
        )
        target = await self._usable(identity, key_field="secret_id", kb=False)
        affected = await knowledge_base_repo.list_by_endpoint(self.db, row.id)
        binding = ProbeBinding.of(
            ProbePurpose.CONNECTION_CHANGE, identity, model=None, dim=None, knowledge_bases=affected
        )
        return await self._run(
            ctx, binding, target, [_Pending(kb, kb.embedding_model) for kb in affected]
        )

    async def _estimate(self, bases: Sequence[KnowledgeBase]) -> EmbeddingProbeEstimate:
        calls = 0
        for kb in bases:
            # A base with nothing stored still costs one call: its width is checked.
            calls += len(await self._sample(kb)) or 1
        return EmbeddingProbeEstimate(
            calls=calls, max_calls=calls * PROBE_ATTEMPTS, knowledge_bases=len(bases)
        )

    async def _sample(self, kb: KnowledgeBase) -> list[StoredChunk]:
        return await self.store.probe_chunks(
            kb.collection_name,
            kb.vector_scope,
            min_length=PROBE_MIN_CHUNK_CHARS,
            shortest=PROBE_SHORT_CHUNKS,
        )

    async def _usable(
        self, identity: TargetIdentity, *, key_field: str, kb: bool
    ) -> EmbeddingTarget:
        """Open the key, or refuse on the field that names why it cannot be had.

        Nothing has been sent by the time this refuses.
        """
        if identity.key_source.is_degraded:
            raise self._unusable(identity.key_source, key_field=key_field, kb=kb)
        target = await open_target(self.db, identity)
        if target.identity.key_source.is_degraded:
            raise self._unusable(target.identity.key_source, key_field=key_field, kb=kb)
        return target

    @staticmethod
    def _unusable(source: EmbeddingKeySource, *, key_field: str, kb: bool) -> BadRequestError:
        field = _KB_FIELDS.get(source, key_field) if kb else key_field
        return refused_field(field, f"Cannot test: {source.explanation}.")

    async def _run(
        self,
        ctx: AuthContext,
        binding: ProbeBinding,
        target: EmbeddingTarget,
        pending: Sequence[_Pending],
    ) -> EmbeddingProbeResult:
        await self._within_budget(target.identity)
        results = [await self._probe_base(item, target) for item in pending]
        return _result(ctx, binding, results)

    async def _within_budget(self, identity: TargetIdentity) -> None:
        """Refuse before the first request when the organization that pays is out of budget.

        A deployment's own keyless endpoint bills nobody.
        """
        payer = identity.key_organization_id
        if payer is not None and identity.key_source in (
            EmbeddingKeySource.ORGANIZATION,
            EmbeddingKeySource.CONNECTION,
        ):
            await assert_organization_within_budget(self.db, payer)

    async def _probe_base(self, item: _Pending, target: EmbeddingTarget) -> KnowledgeBaseProbeRead:
        chunks = await self._sample(item.kb)
        if not chunks:
            return await self._probe_width(item, target)
        calls = 0
        outcome, cosine = ProbeOutcome.VECTORS_DIFFER, None
        for _ in range(PROBE_ATTEMPTS):
            outcome, cosine, made = await self._attempt(item, target, chunks)
            calls += made
            if outcome is ProbeOutcome.PASSED:
                break
        return _read(item.kb, outcome, cosine, calls)

    async def _probe_width(self, item: _Pending, target: EmbeddingTarget) -> KnowledgeBaseProbeRead:
        """A base with no stored chunk: nothing to compare, but its width is fixed.

        The vector column was sized at creation, so a model answering at another
        width would refuse the base's first upload. One request on a fixed text
        settles it; it is repeated once only when the endpoint itself failed.
        """
        calls = 0
        outcome = ProbeOutcome.UNREACHABLE
        for _ in range(PROBE_ATTEMPTS):
            calls += 1
            try:
                vector = await embed_for_probe(
                    base_url=target.identity.base_url,
                    api_key=target.api_key,
                    keyless=target.keyless,
                    model=item.model,
                    text=PROBE_WIDTH_TEXT,
                )
            except EmbeddingProbeError as error:
                outcome = ProbeOutcome(error.outcome)
                continue
            outcome = (
                ProbeOutcome.NO_CHUNKS
                if len(vector) == item.kb.embedding_dim
                else ProbeOutcome.WRONG_WIDTH
            )
            break
        return _read(item.kb, outcome, None, calls)

    async def _attempt(
        self, item: _Pending, target: EmbeddingTarget, chunks: list[StoredChunk]
    ) -> tuple[ProbeOutcome, float | None, int]:
        """One pass over the sample: one request per chunk, stopping at the first that fails."""
        fresh: list[list[float]] = []
        for made, chunk in enumerate(chunks, start=1):
            try:
                vector = await embed_for_probe(
                    base_url=target.identity.base_url,
                    api_key=target.api_key,
                    keyless=target.keyless,
                    model=item.model,
                    text=chunk.content,
                )
            except EmbeddingProbeError as error:
                return ProbeOutcome(error.outcome), None, made
            if len(vector) != len(chunk.embedding):
                return ProbeOutcome.WRONG_WIDTH, None, made
            fresh.append(vector)
        lowest = min_cosine([chunk.embedding for chunk in chunks], fresh)
        outcome = ProbeOutcome.PASSED if lowest >= PROBE_MIN_COSINE else ProbeOutcome.VECTORS_DIFFER
        return outcome, lowest, len(chunks)


def _custom_provider() -> embedding_providers.EmbeddingProviderEntry:
    return next(
        entry
        for entry in embedding_providers.providers()
        if entry.provider == KEY_PURPOSES["openai_compatible"]
    )


def _read(
    kb: KnowledgeBase, outcome: ProbeOutcome, cosine: float | None, calls: int
) -> KnowledgeBaseProbeRead:
    return KnowledgeBaseProbeRead(
        knowledge_base_id=kb.id,
        name=kb.name,
        outcome=outcome.value,
        min_cosine=cosine,
        calls=calls,
    )


def _result(
    ctx: AuthContext, binding: ProbeBinding, bases: list[KnowledgeBaseProbeRead]
) -> EmbeddingProbeResult:
    failed = next((read for read in bases if ProbeOutcome(read.outcome) not in _FINE), None)
    calls = sum(read.calls for read in bases)
    if failed is not None:
        return EmbeddingProbeResult(
            passed=False,
            outcome=failed.outcome,
            dim=None,
            calls=calls,
            knowledge_bases=bases,
            probe_token=None,
            expires_at=None,
        )
    return _passed(ctx, binding, bases, calls=calls)


def _passed(
    ctx: AuthContext, binding: ProbeBinding, bases: list[KnowledgeBaseProbeRead], *, calls: int
) -> EmbeddingProbeResult:
    token, expires_at = mint_probe_token(ctx, binding)
    every_base_empty = all(read.outcome == ProbeOutcome.NO_CHUNKS for read in bases)
    return EmbeddingProbeResult(
        passed=True,
        outcome=(
            ProbeOutcome.NO_CHUNKS if bases and every_base_empty else ProbeOutcome.PASSED
        ).value,
        dim=binding.dim,
        calls=calls,
        knowledge_bases=bases,
        probe_token=token,
        expires_at=expires_at,
    )


def _failed(outcome: ProbeOutcome, *, calls: int, dim: int | None = None) -> EmbeddingProbeResult:
    return EmbeddingProbeResult(
        passed=False,
        outcome=outcome.value,
        dim=dim,
        calls=calls,
        knowledge_bases=[],
        probe_token=None,
        expires_at=None,
    )


def _passed_empty() -> EmbeddingProbeResult:
    """A connection with nothing to compare, such as an OCR server: nothing to prove."""
    return EmbeddingProbeResult(
        passed=True,
        outcome=ProbeOutcome.NO_CHUNKS.value,
        dim=None,
        calls=0,
        knowledge_bases=[],
        probe_token=None,
        expires_at=None,
    )
