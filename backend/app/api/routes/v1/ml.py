"""The ML services, as standalone endpoints (FA-069).

Everything here is reachable by a caller that starts no conversation and runs
no agent: another Urban Stack component with a key, a batch job, a script. The
authentication, the organization header and the permission are the API's own -
there is no second way in for machines, because a surface with its own front
door is a surface with its own mistakes.

One permission gates the four services: `ml:invoke`. It is separate from
`agents:run` on purpose - an integration that parses documents should not
thereby be able to spend the organization's model budget - and every role but
Viewer holds it.

Results are returned and not retained. What is written is the record of the
call, which holds no content and which `GET /ml/calls` reads back.
"""

from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, File, Form, Query, UploadFile

from app.api.deps import Auth, MLSvc, limit_ml_call, require
from app.core.config import settings
from app.core.permissions import Perm
from app.schemas.ml import (
    ChunkingLiteral,
    MLServiceCallList,
    MLServiceCallRead,
    MLServiceCatalogRead,
    MLServiceEntryRead,
    OcrLanguageLiteral,
    ParsedDocumentRead,
    ParserLiteral,
    PiiScanRead,
    PiiScanRequest,
    TranscriptionRead,
)

router = APIRouter()

_READ_CEILING = settings.ML_MAX_UPLOAD_SIZE_MB * 1024 * 1024 + 1
"""How many bytes an upload route copies out of the spooled body.

One byte past the ceiling, so an over-large submission is refused on a length the
service can see without the whole thing having been read into memory first. A
bare `read()` copies the entire spooled file however large it is - the
body-size middleware only refuses a *declared* length, and a chunked request
declares none - so the ceiling has to be applied at the read, not after it.
"""


@router.get(
    "/services",
    response_model=MLServiceCatalogRead,
    dependencies=[Depends(require(Perm.ML_INVOKE))],
)
async def list_ml_services(service: MLSvc) -> Any:
    """The coverage matrix: every required service family, and how far it is delivered.

    Gated on the same permission as the services themselves. It describes the
    deployment rather than any tenant's data, but it is the first call an
    integration makes and the answer names what this build can do - which is
    not a question the surface answers to somebody who may not call it.
    """
    items = [
        MLServiceEntryRead(
            id=entry.id,
            family=entry.family,
            requirements=list(entry.requirements),
            endpoint=entry.endpoint,
            engine=entry.engine,
            state=entry.state.value,
            note=entry.note,
        )
        for entry in service.catalog()
    ]
    return MLServiceCatalogRead(items=items, total=len(items))


@router.post(
    "/documents/analyze",
    response_model=ParsedDocumentRead,
    dependencies=[Depends(require(Perm.ML_INVOKE)), Depends(limit_ml_call)],
)
async def analyze_document(
    service: MLSvc,
    ctx: Auth,
    file: UploadFile = File(..., description="The document to read"),
    parser: ParserLiteral = Form(
        default="liteparse",
        description=(
            "`liteparse` preserves the layout and reads office formats where "
            "LibreOffice is installed; `pymupdf` reads PDFs only and is faster."
        ),
    ),
    chunk_size: int = Form(default=2500, ge=64, le=8000),
    chunk_overlap: int = Form(
        default=200,
        ge=0,
        le=2000,
        description="Must be smaller than `chunk_size`, which the service checks",
    ),
    chunking_strategy: ChunkingLiteral = Form(
        default="recursive",
        description="`recursive`, `fixed`, or `markdown` to split on headings",
    ),
) -> Any:
    """Read a document into pages and prepared chunks, without storing it."""
    document = await service.analyze_document(
        ctx,
        content=await file.read(_READ_CEILING),
        filename=file.filename or "document",
        parser=parser,
        chunk_size=chunk_size,
        chunk_overlap=chunk_overlap,
        chunking_strategy=chunking_strategy,
    )
    return ParsedDocumentRead.of(document)


@router.post(
    "/documents/ocr",
    response_model=ParsedDocumentRead,
    dependencies=[Depends(require(Perm.ML_INVOKE)), Depends(limit_ml_call)],
)
async def recognise_document(
    service: MLSvc,
    ctx: Auth,
    file: UploadFile = File(..., description="The scan, photograph or PDF to read"),
    language: OcrLanguageLiteral = Form(
        default="eng",
        description=(
            "A Tesseract language code, which is three letters. The shipped image "
            "installs `eng` and `pol`; a deployment that installs more packs widens "
            "this list in the same change."
        ),
    ),
    ocr_service_id: UUID | None = Form(
        default=None,
        description=(
            "An OCR server registered under `GET /local-services`, to send the pages "
            "to. Omit to use the recognition engine bundled with the parser."
        ),
    ),
) -> Any:
    """Recognise the text on every page, whether or not it carries a text layer."""
    document = await service.recognise_document(
        ctx,
        content=await file.read(_READ_CEILING),
        filename=file.filename or "document",
        language=language,
        ocr_service_id=ocr_service_id,
    )
    return ParsedDocumentRead.of(document)


@router.post(
    "/audio/transcriptions",
    response_model=TranscriptionRead,
    dependencies=[Depends(require(Perm.ML_INVOKE)), Depends(limit_ml_call)],
)
async def transcribe_recording(
    service: MLSvc,
    ctx: Auth,
    file: UploadFile = File(..., description="The recording to transcribe"),
    provider: str | None = Form(
        default=None,
        description=(
            "The transcription provider to use. Omit for the deployment's first "
            "offered one. The engine is whichever endpoint this organization's model "
            "profile for that provider names, so a self-hosted server is reached the "
            "same way a vendor is."
        ),
    ),
    model: str | None = Form(default=None, description="The model on that provider"),
) -> Any:
    """Turn a recording into text on the organization's own transcription engine."""
    transcript = await service.transcribe(
        ctx,
        content=await file.read(_READ_CEILING),
        filename=file.filename or "recording",
        mime_type=file.content_type or "application/octet-stream",
        provider=provider,
        model=model,
    )
    return TranscriptionRead(
        text=transcript.text, provider=transcript.provider, model=transcript.model
    )


@router.post(
    "/privacy/pii",
    response_model=PiiScanRead,
    dependencies=[Depends(require(Perm.ML_INVOKE)), Depends(limit_ml_call)],
)
async def detect_personal_data(data: PiiScanRequest, service: MLSvc, ctx: Auth) -> Any:
    """Count the personal data in a piece of text, and return it redacted."""
    report = await service.detect_personal_data(ctx, text=data.text, categories=data.categories)
    return PiiScanRead.of(report)


@router.get(
    "/calls",
    response_model=MLServiceCallList,
    dependencies=[Depends(require(Perm.ML_INVOKE))],
)
async def list_ml_calls(
    service: MLSvc,
    ctx: Auth,
    ml_service: str | None = Query(default=None, description="Restrict to one service id"),
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=100),
) -> Any:
    """This organization's ML service calls, newest first."""
    rows, total = await service.call_records(ctx, service=ml_service, skip=skip, limit=limit)
    return MLServiceCallList(
        items=[MLServiceCallRead.model_validate(row) for row in rows], total=total
    )


@router.get(
    "/calls/{call_id}",
    response_model=MLServiceCallRead,
    dependencies=[Depends(require(Perm.ML_INVOKE))],
)
async def get_ml_call(call_id: UUID, service: MLSvc, ctx: Auth) -> Any:
    """One call's status and usage. A call another tenant made is not found."""
    return await service.call_record(ctx, call_id)
