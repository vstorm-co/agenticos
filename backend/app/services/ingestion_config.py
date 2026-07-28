"""How a collection's documents are read, split and described.

Every one of these choices used to be a deployment setting. ``PDF_PARSER`` named
one parser for the whole installation, ``RAG_CHUNK_SIZE`` one chunk size, and
``RAG_IMAGE_DESCRIPTION_MODEL`` one model — read from the environment, invisible
in the product, and the same for a scanned archive of contracts as for a folder
of Markdown notes. This module moves that decision onto the collection, where
the person who owns the documents can see it and change it.

Those variables are gone rather than kept as defaults. Leaving them would have
meant two places to look and one of them unreachable from the product, so the
field defaults below are the only defaults; what stays in ``Settings`` is the
deployment's half — where vectors live, and the credentials and network
addresses a tenant must not choose (see :func:`rag_settings_for`).

Three things are worth stating before reading the models below.

**The parser is per collection and may be overridden per upload; the embedding
model is neither.** Changing which parser reads PDFs affects only documents
ingested afterwards, so an override for one file is meaningful and harmless.
The embedding model is not like that: ``PgVectorStore`` writes
``embedding vector(N)`` into the collection's table at creation, with ``N``
derived from the model name, so a second model either produces vectors that
cannot be written at all or vectors that sit next to the first model's and are
compared against them as though they meant the same thing. It is therefore
recorded on the knowledge base at creation and enforced at ingest — see
:meth:`IngestionConfigService.check_embedding_model`.

**The model comes from a model profile, not from a name.** Everything else on
this platform picks a model by profile id and lets
:class:`app.services.model_profile.ModelProfileService` unseal the credential
for the organization that owns it. Image description was the last caller
constructing ``Agent("some/model")`` and letting Pydantic AI find a key in the
environment, which on a multi-tenant deployment bills one organization's
ingestion to a platform-wide key.

**Image description is off by default.** The deployment flag it replaces
(``RAG_ENABLE_IMAGE_DESCRIPTION``) defaulted to on because it cost nothing to
say so — the model came from ``AI_MODEL`` and the key from the environment.
Turning it on now means choosing a model profile whose key the organization
pays for, which is a decision somebody should make rather than inherit.
"""

from __future__ import annotations

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator
from pydantic_ai.settings import ModelSettings, ThinkingEffort
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.exceptions import BadRequestError
from app.services.model_profile import ModelProfileService
from app.services.rag.config import (
    EMBEDDING_DIMENSIONS,
    EmbeddingsConfig,
    PdfParser,
    RAGSettings,
)
from app.services.rag.documents import DocumentProcessor
from app.services.rag.image_describer import (
    IMAGE_DESCRIPTION_PROMPT,
    BaseImageDescriber,
    PydanticAIImageDescriber,
)

__all__ = [
    "ChunkingStrategy",
    "ImageDescription",
    "ImageDescriptionOverride",
    "IngestionConfig",
    "IngestionConfigService",
    "IngestionOverride",
    "LiteParseOutputFormat",
    "LlamaParseTier",
    "PdfParserName",
    "deployment_defaults",
    "deployment_embedding",
    "parse_override",
]


class PdfParserName(StrEnum):
    """Which of the three implemented parsers reads a PDF.

    ``pymupdf`` is local, fast and free, and the only one that extracts embedded
    images for description. ``llamaparse`` is a cloud service billed per page
    that returns markdown. ``liteparse`` is local and layout-aware, keeping
    tables as ASCII grids rather than flattening them into markdown.
    """

    PYMUPDF = "pymupdf"
    LLAMAPARSE = "llamaparse"
    LITEPARSE = "liteparse"


class LlamaParseTier(StrEnum):
    """LlamaParse's own quality/price ladder. Ignored by the other parsers."""

    FAST = "fast"
    COST_EFFECTIVE = "cost_effective"
    AGENTIC = "agentic"
    AGENTIC_PLUS = "agentic_plus"


class LiteParseOutputFormat(StrEnum):
    """What LiteParse renders a page as.

    ``json`` is the binding's own default and carries bounding boxes we do not
    index, so it is not offered: for RAG the choice is between reconstructed
    markdown and the spatial text grid.
    """

    MARKDOWN = "markdown"
    TEXT = "text"


class ChunkingStrategy(StrEnum):
    """How a parsed page is cut into the pieces that get embedded."""

    RECURSIVE = "recursive"
    MARKDOWN = "markdown"
    FIXED = "fixed"


class ImageDescription(BaseModel):
    """The model that turns pictures inside a document into searchable text."""

    model_config = ConfigDict(extra="forbid")

    model_profile_id: UUID | None = Field(
        default=None,
        description=(
            "Which of the organization's model profiles reads the images; null "
            "uses the organization's default profile."
        ),
    )
    prompt: str = Field(
        default=IMAGE_DESCRIPTION_PROMPT,
        min_length=1,
        max_length=4000,
        description="What the model is asked to say about each image.",
    )
    temperature: float | None = Field(
        default=None,
        ge=0.0,
        le=2.0,
        description=(
            "Unset means the parameter is not sent at all, which is not the same "
            "as sending zero: reasoning models reject temperature outright."
        ),
    )
    thinking: ThinkingEffort | None = Field(
        default=None,
        description=(
            "How hard the model reasons before describing an image. Unset means "
            "no reasoning is requested; a level a provider does not have maps to "
            "its closest one."
        ),
    )

    def model_settings(self) -> ModelSettings:
        """The provider parameters this configuration asks for, and no others.

        Built by omission rather than by defaulting, for the reason
        :class:`app.agents.spec.ModelSettingsSpec` gives: a ``temperature`` key
        with a value nobody chose is a request some models refuse outright.
        """
        chosen: ModelSettings = {}
        if self.temperature is not None:
            chosen["temperature"] = self.temperature
        if self.thinking is not None:
            chosen["thinking"] = self.thinking
        return chosen


class IngestionConfig(BaseModel):
    """What a collection's owner chose. Stored on ``knowledge_bases``.

    The defaults are the values the template shipped as environment defaults, so
    a collection created without an opinion behaves as this platform always did
    — with the single exception noted in the module docstring.
    """

    model_config = ConfigDict(extra="forbid")

    pdf_parser: PdfParserName = Field(
        default=PdfParserName.PYMUPDF,
        description="Which parser reads PDFs. Other formats use the built-in readers.",
    )
    ocr: bool = Field(
        default=False,
        description=(
            "Read scanned pages as images. PyMuPDF falls back to the image model "
            "for a page with almost no text; LiteParse runs its own OCR."
        ),
    )
    llamaparse_tier: LlamaParseTier = Field(
        default=LlamaParseTier.AGENTIC,
        description="LlamaParse quality tier. Ignored by the other parsers.",
    )
    auto_ocr: bool = Field(
        default=True,
        description=(
            "Let LiteParse decide per document whether OCR is needed, using its "
            "cheap text-layer check. OCR dominates the cost of a parse and most "
            "documents are born digital and need none of it. Turn this off to "
            "OCR every page unconditionally."
        ),
    )
    ocr_language: str = Field(
        default="eng",
        pattern=r"^[a-z]{3}(\+[a-z]{3})*$",
        description=(
            "Tesseract language code for LiteParse's OCR — three letters, "
            "'eng' not 'en', and '+'-joined for several ('eng+pol')."
        ),
    )
    liteparse_output_format: LiteParseOutputFormat = Field(
        default=LiteParseOutputFormat.MARKDOWN,
        description=(
            "What LiteParse returns. Markdown reconstructs headings, tables and "
            "lists from the layout, which is what the markdown chunking strategy "
            "splits on; text keeps the spatial grid instead."
        ),
    )
    liteparse_dpi: float = Field(
        default=150.0,
        ge=72.0,
        le=600.0,
        description="Rendering resolution for OCR. Higher reads faint scans; slower.",
    )
    max_pages: int = Field(
        default=1000,
        ge=1,
        le=10000,
        description=(
            "Pages LiteParse reads before it stops. The setting that actually "
            "bounds the cost of one document — the timeout only bounds the wait."
        ),
    )
    parse_timeout_seconds: float = Field(
        default=600.0,
        gt=0.0,
        le=3600.0,
        description="How long LiteParse may spend on one document.",
    )
    chunk_size: int = Field(
        default=512, ge=64, le=8192, description="Characters per embedded chunk."
    )
    chunk_overlap: int = Field(
        default=50,
        ge=0,
        le=4096,
        description="Characters each chunk repeats from the previous one.",
    )
    chunking_strategy: ChunkingStrategy = Field(default=ChunkingStrategy.RECURSIVE)
    describe_images: bool = Field(
        default=False,
        description=(
            "Send images found in a document to a model and index what it says. "
            "Requires a usable model profile, which is checked when this is set."
        ),
    )
    image_description: ImageDescription = Field(default_factory=ImageDescription)

    @model_validator(mode="after")
    def overlap_fits_inside_a_chunk(self) -> IngestionConfig:
        """An overlap at least as large as the chunk never terminates.

        ``RecursiveCharacterTextSplitter`` warns and then produces chunks that
        each start where the previous one did, so a document either grows
        without bound or is silently cut wrong. Refusing the pair here means the
        form is what says so.
        """
        if self.chunk_overlap >= self.chunk_size:
            raise ValueError(
                f"chunk_overlap ({self.chunk_overlap}) must be smaller than "
                f"chunk_size ({self.chunk_size})"
            )
        return self


class ImageDescriptionOverride(BaseModel):
    """The image-description fields for one upload; unset fields inherit.

    ``None`` is a value here, not an absence: sending ``model_profile_id: null``
    asks for the organization's default profile even when the collection names a
    specific one. Omitting the key inherits. Pydantic's ``model_fields_set`` is
    what tells the two apart, which is why the merge below uses
    ``exclude_unset``.
    """

    model_config = ConfigDict(extra="forbid")

    model_profile_id: UUID | None = None
    prompt: str | None = Field(default=None, min_length=1, max_length=4000)
    temperature: float | None = Field(default=None, ge=0.0, le=2.0)
    thinking: ThinkingEffort | None = None

    def applied_to(self, base: ImageDescription) -> ImageDescription:
        return base.model_copy(update=self.model_dump(exclude_unset=True))


class IngestionOverride(BaseModel):
    """One upload's departures from its collection's configuration.

    Everything the collection can be configured with is here except the
    embedding model, which is not a per-document choice — see the module
    docstring. An empty override is the ordinary case and means "as configured".
    """

    model_config = ConfigDict(extra="forbid")

    pdf_parser: PdfParserName | None = None
    ocr: bool | None = None
    llamaparse_tier: LlamaParseTier | None = None
    auto_ocr: bool | None = None
    ocr_language: str | None = Field(default=None, pattern=r"^[a-z]{3}(\+[a-z]{3})*$")
    liteparse_output_format: LiteParseOutputFormat | None = None
    liteparse_dpi: float | None = Field(default=None, ge=72.0, le=600.0)
    max_pages: int | None = Field(default=None, ge=1, le=10000)
    parse_timeout_seconds: float | None = Field(default=None, gt=0.0, le=3600.0)
    chunk_size: int | None = Field(default=None, ge=64, le=8192)
    chunk_overlap: int | None = Field(default=None, ge=0, le=4096)
    chunking_strategy: ChunkingStrategy | None = None
    describe_images: bool | None = None
    image_description: ImageDescriptionOverride | None = None

    @property
    def is_empty(self) -> bool:
        """Whether this override asks for anything at all.

        A document records the override it was ingested with, and recording an
        object that says nothing would make every upload look like a departure.
        """
        return not self.model_fields_set

    def applied_to(self, base: IngestionConfig) -> IngestionConfig:
        """The configuration this upload actually runs with.

        Re-validated rather than copied, because the merged pair is what has to
        be legal: a collection with ``chunk_size=512`` and an override setting
        ``chunk_overlap=600`` is two individually valid numbers and one
        configuration that does not terminate.
        """
        changes = self.model_dump(exclude_unset=True, exclude={"image_description"})
        if self.image_description is not None:
            changes["image_description"] = self.image_description.applied_to(base.image_description)
        return IngestionConfig.model_validate({**base.model_dump(), **changes})


def parse_override(raw: str | None) -> IngestionOverride | None:
    """Read a per-upload override off a multipart form field.

    An upload is ``multipart/form-data``, so its settings cannot travel as a
    JSON body next to the file. They travel as one field holding JSON rather
    than as a dozen flat fields, so the wire format is the same shape as the
    stored configuration and the nested image-description group survives.

    Raises:
        BadRequestError: If the field is not valid JSON for an override. Silently
            ignoring it would ingest the document with the collection's settings
            while the caller believed otherwise, which is the one outcome an
            override must never have.
    """
    if raw is None or not raw.strip():
        return None
    try:
        return IngestionOverride.model_validate_json(raw)
    except ValidationError as exc:
        raise BadRequestError(
            message="The 'ingestion' field is not a valid ingestion override",
            details={"errors": exc.errors(include_url=False, include_input=False)},
        ) from exc


def deployment_defaults() -> IngestionConfig:
    """The configuration a collection gets when nobody chooses one.

    Deliberately not read from the environment. How a collection parses its
    documents is a per-collection choice that lives on the row, and an
    installation-wide `PDF_PARSER`/`RAG_CHUNK_SIZE` is a leftover from the
    template this project was generated from: it makes the same form produce
    different collections on two deployments, and there is nowhere in the
    product to see or change it.

    The field defaults on :class:`IngestionConfig` are therefore the only
    defaults. Anyone wanting different ones sets them on the collection, where
    they are visible, auditable and per tenant.
    """
    return IngestionConfig()


def deployment_embedding() -> tuple[str, int]:
    """The embedding model this deployment indexes with, and its dimension.

    Recorded on every collection at creation. The dimension travels with the
    name because ``EMBEDDING_DIMENSIONS`` is a lookup table that can gain
    entries: a collection built today must keep the number its table was
    actually created with, not the one a later release would derive.

    Raises:
        BadRequestError: If the configured model has no known dimension. The
            vector column would otherwise be created at the default width and
            every insert into it would fail on a mismatch nobody could trace
            back to a typo in an environment variable.
    """
    model = settings.EMBEDDING_MODEL
    if model not in EMBEDDING_DIMENSIONS:
        raise BadRequestError(
            message=(
                f"EMBEDDING_MODEL is set to '{model}', whose vector width this build does "
                "not know. Collections would be created at the default width and every "
                "document indexed into them would be rejected."
            ),
            details={"model": model, "known": sorted(EMBEDDING_DIMENSIONS)},
        )
    return model, EMBEDDING_DIMENSIONS[model]


def rag_settings_for(config: IngestionConfig) -> RAGSettings:
    """Turn a collection's choices into the settings object the pipeline takes.

    The two values deliberately *not* taken from the configuration are the
    LlamaParse API key and the LiteParse OCR server URL. The first is a
    deployment credential; the second is an address on the deployment's own
    network, and letting a tenant choose one is the request forgery this
    platform refuses everywhere else (:func:`app.core.sanitize.validate_webhook_url`).
    """
    return RAGSettings(
        chunk_size=config.chunk_size,
        chunk_overlap=config.chunk_overlap,
        chunking_strategy=config.chunking_strategy.value,
        enable_ocr=config.ocr,
        embeddings_config=EmbeddingsConfig(model=settings.EMBEDDING_MODEL),
        pdf_parser=PdfParser(
            method=config.pdf_parser.value,
            api_key=settings.LLAMAPARSE_API_KEY,
            tier=config.llamaparse_tier.value,
            liteparse_ocr_server_url=settings.LITEPARSE_OCR_SERVER_URL or None,
            liteparse_ocr_language=config.ocr_language,
            liteparse_timeout_seconds=config.parse_timeout_seconds,
            liteparse_auto_ocr=config.auto_ocr,
            liteparse_output_format=config.liteparse_output_format.value,
            liteparse_dpi=config.liteparse_dpi,
            liteparse_max_pages=config.max_pages,
        ),
        enable_image_description=config.describe_images,
    )


class IngestionConfigService:
    """Resolves a configuration into the things that actually run.

    Three jobs, and they are separate on purpose: proving a configuration is
    usable while a form is still open, refusing a collection whose vectors a new
    embedding model would invalidate, and building the parser a worker runs.
    """

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def resolved_image_model(
        self, organization_id: UUID, config: IngestionConfig
    ) -> str | None:
        """The ``provider:model`` image description will use, or ``None`` if off.

        Called when a configuration is *set* rather than when it is used, which
        is this platform's habit: a model profile that does not resolve is a
        form error here and an unexplained ingestion failure an hour later
        otherwise. The string it returns is recorded on every document the
        configuration produces, because a profile can be edited or deleted and
        the transcript of what read a document should not change with it.

        Raises:
            NotFoundError: If the named profile is not this organization's, or
                image description is on and the organization has no default.
            BadRequestError: If the profile has no usable credential behind it.
        """
        if not config.describe_images:
            return None
        spec = await ModelProfileService(self.db).resolve_for_organization(
            organization_id, profile_id=config.image_description.model_profile_id
        )
        return f"{spec.provider}:{spec.model}"

    def check_embedding_model(self, *, collection: str, built_with: str) -> None:
        """Refuse to index into a collection with a model it was not built for.

        The failure this prevents is silent and total. ``PgVectorStore`` reads
        its dimension from the deployment's ``EMBEDDING_MODEL``: change that
        variable and every existing collection either rejects inserts outright,
        because the column is a different width, or — between two models that
        happen to share a width — accepts vectors from a different space and
        compares them against the old ones as though the numbers meant the same
        thing. The second is worse, because search keeps answering.

        Raises:
            BadRequestError: If the deployment's model is no longer the one this
                collection's vectors were produced by.
        """
        current = settings.EMBEDDING_MODEL
        if current == built_with:
            return
        raise BadRequestError(
            message=(
                f"Collection '{collection}' was indexed with '{built_with}' and this "
                f"deployment now embeds with '{current}'. Vectors from the two are not "
                "comparable, so nothing more can be added to it: either restore "
                f"EMBEDDING_MODEL to '{built_with}', or create a new collection and "
                "re-ingest its documents."
            ),
            details={"collection": collection, "built_with": built_with, "configured": current},
        )

    async def build_describer(
        self, organization_id: UUID | None, config: IngestionConfig
    ) -> BaseImageDescriber | None:
        """The image describer this configuration asks for, credentials included.

        Resolved here rather than carried from the request that accepted the
        upload: a sealed credential must not travel through a task argument, and
        the organization that owns the document is enough to unseal it.

        Raises:
            BadRequestError: If the configuration asks for image description and
                the ingestion has no organization to resolve a profile in — a
                document ingested by a connector sync that predates organization
                stamping, say. Refusing is the point: the alternative is a
                document indexed with its diagrams silently missing, which looks
                exactly like a document whose diagrams were never there.
        """
        if not config.describe_images:
            return None
        if organization_id is None:
            raise BadRequestError(
                message=(
                    "This collection describes the images in its documents, and this "
                    "ingestion has no organization to resolve a model profile in."
                ),
                details={"model_profile_id": str(config.image_description.model_profile_id)},
            )
        spec = await ModelProfileService(self.db).resolve_for_organization(
            organization_id, profile_id=config.image_description.model_profile_id
        )
        return PydanticAIImageDescriber(
            model=spec.build(),
            prompt=config.image_description.prompt,
            model_settings={**spec.params, **config.image_description.model_settings()},
        )

    async def build_processor(
        self, organization_id: UUID | None, config: IngestionConfig
    ) -> DocumentProcessor:
        """The parser/chunker pair a document is about to be run through."""
        return DocumentProcessor(
            settings=rag_settings_for(config),
            image_describer=await self.build_describer(organization_id, config),
        )
