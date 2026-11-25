"""Durable, owner-scoped ZIP transfers; queue work and imported writes commit together."""

import hashlib
import json
from collections.abc import AsyncIterator
from contextlib import aclosing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from uuid import UUID, uuid4

from anyio import TemporaryDirectory, open_file
from pydantic import JsonValue, TypeAdapter
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.blocking import run_blocking_settled
from app.core.exceptions import (
    AuthenticationError,
    AuthorizationError,
    BadRequestError,
    ConflictError,
    NotFoundError,
)
from app.core.permissions import AuthContext, Perm
from app.db.models.portability_operation import PortabilityOperation
from app.repositories import background_job as jobs
from app.repositories import member_repo, user_repo
from app.repositories import portability_operation as operations
from app.schemas.portability_operation import (
    BundleApplyCreate,
    BundleExportStart,
    BundleUploadStart,
    PortabilityOperationRead,
    TransferDirection,
)
from app.schemas.resource_bundle import (
    BundleDownloadCreate,
    BundleImportCreate,
    BundleImportRead,
    BundleResource,
    ResourceBundle,
)
from app.services.api_key import ApiKeyService
from app.services.background_jobs import enqueue
from app.services.file_storage import BaseFileStorage, get_file_storage
from app.services.portability.archive import BundleLimits, open_bundle, write_bundle
from app.services.portability.contracts import require_agent_root, verify_references
from app.services.portability.facade import PortabilityService
from app.services.portability.file_bundle import hydrate_text
from app.worker.jobs import PORTABLE_TRANSFER, PortableTransferPayload

_OBJECT = TypeAdapter(dict[str, JsonValue])
_MAX_OPEN = 3
_LIFETIME = timedelta(hours=24)


def _request_hash(request: dict[str, JsonValue]) -> str:
    return hashlib.sha256(
        json.dumps(request, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _write_zip(path: Path, bundle: ResourceBundle, files: dict[str, Path]) -> None:
    with path.open("w+b") as target:
        write_bundle(target, bundle, files)


def _read_zip(path: Path, directory: Path) -> tuple[ResourceBundle, dict[str, Path]]:
    files: dict[str, Path] = {}
    with path.open("rb") as source, open_bundle(source) as archive:
        verify_references(archive.manifest)
        require_agent_root(archive.manifest)
        for asset in archive.manifest.assets:
            # Archive paths are never extracted. Only validated digests become
            # locally minted filenames, and duplicate contents are stored once.
            if asset.sha256 in files:
                continue
            target = directory / asset.sha256
            with target.open("xb") as output:
                for chunk in archive.asset_chunks(asset):
                    output.write(chunk)
            files[asset.sha256] = target
        return archive.manifest, files


class PortableTransferService:
    def __init__(self, db: AsyncSession, *, storage: BaseFileStorage | None = None) -> None:
        self.db = db
        self.storage = storage or get_file_storage()
        self.portability = PortabilityService(db)

    @staticmethod
    def _require(ctx: AuthContext) -> None:
        if ctx.user_id is None or not ctx.has(Perm.AGENTS_EDIT):
            raise AuthorizationError(message="Resource transfers require a signed-in agent editor")

    async def _owned(
        self, ctx: AuthContext, identity: UUID, *, lock: bool = False
    ) -> PortabilityOperation:
        self._require(ctx)
        row = await operations.get(
            self.db,
            identity,
            organization_id=ctx.organization_id,
            user_id=ctx.subject_id,
            for_update=lock,
        )
        if row is None:
            raise NotFoundError(message="This transfer is not available")
        if row.expires_at <= datetime.now(UTC):
            raise ConflictError(message="This transfer expired; start a new transfer")
        # A narrower API key cannot inherit a browser session's transfer.
        if row.api_key_id != ctx.api_key_id:
            raise AuthorizationError(
                message="Use the same sign-in method that started this transfer"
            )
        return row

    async def _start(
        self,
        ctx: AuthContext,
        *,
        request_id: UUID,
        direction: TransferDirection,
        request: dict[str, JsonValue],
    ) -> tuple[PortabilityOperation, bool]:
        self._require(ctx)
        await operations.lock_owner(
            self.db, organization_id=ctx.organization_id, user_id=ctx.subject_id
        )
        previous = await operations.for_request(
            self.db,
            organization_id=ctx.organization_id,
            user_id=ctx.subject_id,
            request_id=request_id,
        )
        digest = _request_hash(request)
        if previous is not None:
            row = await self._owned(ctx, previous.id)
            if row.request_hash != digest or row.direction != direction:
                raise ConflictError(
                    message="This request ID already identifies a different transfer"
                )
            return row, False
        if (
            await operations.count_open(
                self.db,
                organization_id=ctx.organization_id,
                user_id=ctx.subject_id,
                now=datetime.now(UTC),
            )
            >= _MAX_OPEN
        ):
            raise ConflictError(message="Finish your open transfers before starting another")
        row = await operations.create(
            self.db,
            identity=uuid4(),
            organization_id=ctx.organization_id,
            user_id=ctx.subject_id,
            api_key_id=ctx.api_key_id,
            request_id=request_id,
            request_hash=digest,
            direction=direction,
            status="awaiting_upload" if direction == "import" else "queued",
            request=request,
            expires_at=datetime.now(UTC) + _LIFETIME,
        )
        return row, True

    async def start_export(
        self, ctx: AuthContext, request: BundleExportStart
    ) -> PortabilityOperationRead:
        self._require(ctx)
        if request.root_kind != "agent":
            raise BadRequestError(message="Workflow ZIP exports are not available yet")
        # Check root authority before persisting work; it is checked again by
        # the worker and before download, against current resource grants.
        await self.portability.export_agent(ctx, request.root_id, metadata_only=True)
        row, created = await self._start(
            ctx,
            request_id=request.request_id,
            direction="export",
            request=_OBJECT.validate_python(request.model_dump(mode="json")),
        )
        if created:
            await self._queue(row)
        return await self._read(ctx, row)

    async def start_upload(
        self, ctx: AuthContext, request: BundleUploadStart
    ) -> PortabilityOperationRead:
        row, _ = await self._start(
            ctx,
            request_id=request.request_id,
            direction="import",
            request=_OBJECT.validate_python(request.model_dump(mode="json")),
        )
        return await self._read(ctx, row)

    async def upload(
        self, ctx: AuthContext, identity: UUID, chunks: AsyncIterator[bytes]
    ) -> PortabilityOperationRead:
        row = await self._owned(ctx, identity, lock=True)
        if row.status != "awaiting_upload":
            raise ConflictError(message="This transfer has already received an upload")
        request = BundleUploadStart.model_validate(row.request)
        path = f"portability/{row.id}/staging/{uuid4()}/source.zip"
        async with TemporaryDirectory(prefix="agenticos-transfer-") as directory:
            temporary = Path(directory) / "source.zip"
            digest = hashlib.sha256()
            length = 0
            async with await open_file(temporary, "wb") as target:
                async for chunk in chunks:
                    length += len(chunk)
                    if length > request.size_bytes:
                        raise BadRequestError(message="The uploaded file exceeds its declared size")
                    digest.update(chunk)
                    await target.write(chunk)
            if length != request.size_bytes:
                raise BadRequestError(message="The uploaded file is incomplete")
            await self._save(path, temporary)
        row.source_path, row.source_sha256, row.source_bytes = path, digest.hexdigest(), length
        row.total_bytes = length
        row.status = "queued"
        await self._queue(row)
        return await self._read(ctx, row)

    async def _queue(self, row: PortabilityOperation) -> None:
        assert row.organization_id is not None
        job = await enqueue(
            self.db,
            PORTABLE_TRANSFER,
            PortableTransferPayload(
                operation_id=row.id, organization_id=row.organization_id, revision=row.revision
            ),
            organization_id=row.organization_id,
        )
        assert job is not None
        row.job_id = job
        await operations.save(self.db, row)

    async def get(self, ctx: AuthContext, identity: UUID) -> PortabilityOperationRead:
        return await self._read(ctx, await self._owned(ctx, identity))

    async def _read(self, ctx: AuthContext, row: PortabilityOperation) -> PortabilityOperationRead:
        preview = None
        if row.manifest is not None and row.direction == "import":
            preview = await self.portability.preview_import(
                ctx, ResourceBundle.model_validate(row.manifest)
            )
        return PortabilityOperationRead.model_validate(row).model_copy(
            update={
                "preview": preview,
                "receipt": BundleImportRead.model_validate(row.result)
                if row.result is not None
                else None,
                "can_download": row.direction == "export" and row.status == "ready",
            }
        )

    async def apply(
        self, ctx: AuthContext, identity: UUID, request: BundleApplyCreate
    ) -> PortabilityOperationRead:
        row = await self._owned(ctx, identity, lock=True)
        choices = _OBJECT.validate_python(
            {key: value.model_dump(mode="json") for key, value in request.choices.items()}
        )
        if row.phase == "apply" and row.choices == choices:
            return await self._read(ctx, row)
        if row.status != "review" or row.revision != request.expected_revision:
            raise ConflictError(message="This transfer changed; reload its review before importing")
        row.choices = choices
        row.phase, row.status = "apply", "queued"
        row.revision += 1
        await self._queue(row)
        return await self._read(ctx, row)

    async def download(self, ctx: AuthContext, identity: UUID) -> AsyncIterator[bytes]:
        row = await self._owned(ctx, identity)
        if (
            row.direction != "export"
            or row.status != "ready"
            or row.output_path is None
            or row.manifest is None
        ):
            raise ConflictError(message="This export is not ready to download")
        bundle = ResourceBundle.model_validate(row.manifest)
        for item in bundle.resources:
            if item.definition is not None:
                # A stored archive does not freeze the owner's read authority.
                await self.portability.sources.read(ctx, item, with_content=False)
        return await self.storage.open_stream(row.output_path)

    async def context(self, row: PortabilityOperation) -> AuthContext:
        if row.organization_id is None or row.user_id is None:
            raise AuthenticationError(message="The transfer owner no longer exists")
        if row.api_key_id is not None:
            ctx = await ApiKeyService(self.db).context_for_key(
                row.api_key_id, organization_id=row.organization_id
            )
            if ctx.subject_id != row.user_id:
                raise AuthenticationError(message="The transfer key no longer identifies its owner")
        else:
            membership = await member_repo.get_active(
                self.db, organization_id=row.organization_id, user_id=row.user_id
            )
            user = await user_repo.get_by_id(self.db, row.user_id)
            if membership is None or user is None or not user.is_active:
                raise AuthenticationError(message="The transfer owner no longer has access")
            ctx = AuthContext(
                user_id=row.user_id,
                organization_id=row.organization_id,
                role=membership.role,
                is_app_admin=user.is_app_admin,
            )
        self._require(ctx)
        return ctx

    async def claim(self, payload: PortableTransferPayload, *, attempt: int) -> bool:
        row = await operations.get_for_worker(self.db, payload.operation_id, for_update=True)
        if (
            row is None
            or row.organization_id != payload.organization_id
            or row.revision != payload.revision
            or row.status != "queued"
        ):
            return False
        if row.expires_at <= datetime.now(UTC) + timedelta(minutes=30):
            raise ConflictError(
                message="This transfer is too close to expiry; start a new transfer"
            )
        await self.context(row)
        row.status, row.worker_attempt = "running", attempt
        await operations.save(self.db, row)
        return True

    async def run(self, payload: PortableTransferPayload, *, attempt: int) -> None:
        row = await operations.get_for_worker(self.db, payload.operation_id)
        if (
            row is None
            or row.organization_id != payload.organization_id
            or row.revision != payload.revision
            or row.status not in ("queued", "running")
        ):
            return
        ctx = await self.context(row)
        if row.expires_at <= datetime.now(UTC) + timedelta(minutes=30):
            raise ConflictError(
                message="This transfer is too close to expiry; start a new transfer"
            )
        async with TemporaryDirectory(prefix="agenticos-transfer-") as directory:
            root = Path(directory)
            if row.direction == "export":
                request = BundleExportStart.model_validate(row.request)
                bundle, files = await self.portability.selected_agent(
                    ctx,
                    request.root_id,
                    BundleDownloadCreate(resources=request.resources, file_format="json"),
                    asset_directory=root,
                )
                output = root / "output.zip"
                await run_blocking_settled(_write_zip, output, bundle, files)
                output_path = f"portability/{row.id}/staging/{attempt}/output.zip"
                await self._save(output_path, output)
                size = await run_blocking_settled(lambda: output.stat().st_size)
                result = None
            else:
                assert row.source_path is not None
                uploaded = root / "source.zip"
                await self._stage_source(row, uploaded)
                bundle, files = await run_blocking_settled(_read_zip, uploaded, root)
                output_path = None
                size = row.source_bytes
                result = None
                if row.phase == "apply":

                    async def hydrate(resource: BundleResource) -> BundleResource:
                        single = ResourceBundle.model_construct(
                            roots=(resource.key,),
                            resources=(resource,),
                            assets=tuple(
                                asset for asset in bundle.assets if asset.resource == resource.key
                            ),
                        )
                        content = await run_blocking_settled(hydrate_text, single, files)
                        return content.resources[0]

                    # Imported resources and their receipt commit only after the
                    # final lease check. Do not block heartbeats during the import.
                    result = await self.portability.import_agent(
                        ctx,
                        BundleImportCreate.model_validate(
                            {"operation_id": row.id, "bundle": bundle, "choices": row.choices}
                        ),
                        hydrate=hydrate,
                    )
            await self._fence(row, payload, attempt)
            row.manifest = _OBJECT.validate_python(bundle.model_dump(mode="json"))
            row.output_path = output_path
            row.completed_bytes = row.total_bytes = size
            row.result = (
                _OBJECT.validate_python(result.model_dump(mode="json"))
                if result is not None
                else None
            )
            row.status = "ready" if row.direction == "export" or result is not None else "review"
            row.worker_attempt = attempt
            await operations.save(self.db, row)

    async def _fence(
        self, row: PortabilityOperation, payload: PortableTransferPayload, attempt: int
    ) -> None:
        if (
            row.job_id is None
            or await jobs.lock_attempt(self.db, row.job_id, attempt=attempt) is None
        ):
            raise ConflictError(message="This transfer's worker lease ended")
        current = await operations.get_for_worker(self.db, row.id, for_update=True)
        if (
            current is None
            or current.organization_id != payload.organization_id
            or current.revision != payload.revision
            or current.status not in ("queued", "running")
        ):
            raise ConflictError(message="This transfer changed while the worker was running")
        await self.context(current)

    async def _save(self, path: str, source: Path) -> None:
        async with await open_file(source, "rb") as stream:
            await self.storage.save_stream_at(path, stream.wrapped)

    async def _stage_source(self, row: PortabilityOperation, destination: Path) -> None:
        assert row.source_path is not None
        stream = await self.storage.open_stream(row.source_path)
        digest = hashlib.sha256()
        length = 0
        async with aclosing(stream), await open_file(destination, "wb") as output:
            async for chunk in stream:
                length += len(chunk)
                if length > BundleLimits().compressed_bytes or length > row.source_bytes:
                    raise BadRequestError(message="The stored upload exceeds its recorded size")
                digest.update(chunk)
                await output.write(chunk)
        if length != row.source_bytes or digest.hexdigest() != row.source_sha256:
            raise BadRequestError(message="The stored upload does not match its recorded digest")

    async def settle(self, payload: PortableTransferPayload) -> None:
        row = await operations.get_for_worker(self.db, payload.operation_id, for_update=True)
        if (
            row is not None
            and row.organization_id == payload.organization_id
            and row.revision == payload.revision
            and row.status in ("queued", "running")
        ):
            row.status = "failed"
            row.error_code = "transfer_failed"
            await operations.save(self.db, row)

    async def sweep(self) -> None:
        for candidate in await operations.expired(self.db, now=datetime.now(UTC)):
            row = await operations.get_for_worker(self.db, candidate.id, for_update=True)
            if row is None:
                continue
            # The prefix is minted from the journal's UUID; no submitted path can
            # broaden cleanup. Expiry exceeds the maximum worker duration.
            await self.storage.delete_prefix(f"portability/{row.id}/")
            await operations.delete(self.db, row)
