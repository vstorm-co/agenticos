"""RAG configuration."""

from enum import StrEnum

from pydantic import BaseModel, Field, model_validator


class DocumentExtensions(StrEnum):
    """Extensions supported by the RAG ingestion pipeline."""

    PDF = ".pdf"
    DOCX = ".docx"
    MD = ".md"
    TXT = ".txt"


# Extensions read by the built-in Python parsers, whichever PDF parser is
# configured: `TextDocumentParser` and `DocxDocumentParser` handle these and
# the parser choice never enters into it.
NATIVE_FORMATS: set[str] = {".txt", ".md", ".docx"}

# Extensions each PDF parser is routed for, *in addition* to the native ones.
#
# These sets are a promise, not a wish list: `/rag/supported-formats`
# advertises them, `RAGDocumentService.upload` accepts on them, and
# `DocumentProcessor.process_file` has to be able to route every one. They
# used to be aspirational - LiteParse claimed `.xlsx`/`.pptx`/images and
# LlamaParse claimed thirty formats down to `.mp3`, while `process_file`
# routed four extensions and raised `ValueError` on everything else. Nothing
# refused the upload: the file was stored, a document row was created and the
# ingestion task was dispatched, so the failure surfaced in a worker minutes
# later as a document stuck at "processing" with no explanation on screen.
#
# `tests/services/test_supported_formats.py` pins each set against what the
# pipeline actually routes, so widening one here without teaching the parser
# fails the suite rather than the user's upload.
PYMUPDF_PDF_FORMATS: set[str] = {".pdf"}

# LiteParse reads PDFs directly through PDFium and converts everything else to
# PDF first. The two conversion paths differ in what they need installed, which
# is the only reason they are separate constants: images are converted by the
# Rust core itself (`crates/liteparse/src/conversion.rs`, native since v2.8.0),
# while office documents are converted by shelling out to LibreOffice, so those
# formats are readable only where LibreOffice is on PATH.
#
# `LiteParseParser.libreoffice_available()` is what answers that at runtime;
# advertising the union and probing is better than advertising the intersection,
# because the intersection would hide `.docx` support from every deployment that
# does have LibreOffice.
LITEPARSE_IMAGE_FORMATS: set[str] = {
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".bmp",
    ".tiff",
    ".tif",
    ".webp",
    ".svg",
}

# Mirrors OFFICE_EXTENSIONS + PRESENTATION_EXTENSIONS + SPREADSHEET_EXTENSIONS
# in liteparse's `conversion.rs`. Kept in that order so the two can be diffed.
LITEPARSE_OFFICE_FORMATS: set[str] = {
    # Word processing
    ".doc",
    ".docx",
    ".docm",
    ".dot",
    ".dotm",
    ".dotx",
    ".odt",
    ".ott",
    ".rtf",
    ".pages",
    # Presentations
    ".ppt",
    ".pptx",
    ".pptm",
    ".pot",
    ".potm",
    ".potx",
    ".odp",
    ".otp",
    ".key",
    # Spreadsheets
    ".xls",
    ".xlsx",
    ".xlsm",
    ".xlsb",
    ".ods",
    ".ots",
    ".csv",
    ".tsv",
    ".numbers",
}

LITEPARSE_PDF_FORMATS: set[str] = {".pdf"} | LITEPARSE_IMAGE_FORMATS | LITEPARSE_OFFICE_FORMATS

# LlamaParse uploads the file and lets the cloud service identify it, so the
# extension list is a genuine capability rather than local routing. It stays
# narrower than the ~130 formats LlamaParse markets: this is the set the
# integration is wired and tested for.
LLAMAPARSE_PDF_FORMATS: set[str] = {
    ".pdf",
    ".doc",
    ".pptx",
    ".ppt",
    ".rtf",
    ".epub",
    ".jpg",
    ".jpeg",
    ".png",
    ".html",
    ".htm",
    ".xlsx",
    ".xls",
    ".csv",
}

PYMUPDF_FORMATS: set[str] = NATIVE_FORMATS | PYMUPDF_PDF_FORMATS
LITEPARSE_FORMATS: set[str] = NATIVE_FORMATS | LITEPARSE_PDF_FORMATS
LLAMAPARSE_FORMATS: set[str] = NATIVE_FORMATS | LLAMAPARSE_PDF_FORMATS

PARSER_FORMATS: dict[str, set[str]] = {
    "pymupdf": PYMUPDF_FORMATS,
    "liteparse": LITEPARSE_FORMATS,
    "llamaparse": LLAMAPARSE_FORMATS,
}

PARSER_PDF_FORMATS: dict[str, set[str]] = {
    "pymupdf": PYMUPDF_PDF_FORMATS,
    "liteparse": LITEPARSE_PDF_FORMATS,
    "llamaparse": LLAMAPARSE_PDF_FORMATS,
}


def get_supported_formats(parser_name: str = "pymupdf") -> set[str]:
    """Get supported file formats for a given parser."""
    return PARSER_FORMATS.get(parser_name, PYMUPDF_FORMATS)


# Known embedding models and their output dimensions.
# Used to auto-set vector store dimension from model name.
EMBEDDING_DIMENSIONS: dict[str, int] = {
    "text-embedding-3-small": 1536,
    "text-embedding-3-large": 3072,
    "text-embedding-ada-002": 1536,
    "voyage-3": 1024,
    "voyage-3-lite": 512,
    "voyage-code-3": 1024,
    "gemini-embedding-exp-03-07": 3072,
    "all-MiniLM-L6-v2": 384,
    "all-mpnet-base-v2": 768,
    "bge-small-en-v1.5": 384,
    "bge-base-en-v1.5": 768,
    "bge-large-en-v1.5": 1024,
}


class EmbeddingsConfig(BaseModel):
    """Embeddings configuration. Dimension is auto-derived from model name."""

    model: str = "text-embedding-3-large"
    dim: int = 3072

    @model_validator(mode="after")
    def set_dim_from_model(self) -> "EmbeddingsConfig":
        if self.model in EMBEDDING_DIMENSIONS:
            self.dim = EMBEDDING_DIMENSIONS[self.model]
        return self


class DocumentParser(BaseModel):
    """Document parsing settings (non-PDF files)."""

    method: str = "python_native"


class PdfParser(BaseModel):
    """PDF parsing settings."""

    method: str = "pymupdf"  # Runtime: pymupdf, llamaparse, liteparse
    api_key: str = ""
    tier: str = "agentic"
    # LiteParse-specific. ocr_server_url=None falls back to bundled Tesseract.
    # Set to e.g. "http://easyocr:8000" to use an external OCR microservice.
    liteparse_ocr_server_url: str | None = None
    # Tesseract language codes are three letters: "eng", not "en".
    liteparse_ocr_language: str = "eng"
    liteparse_timeout_seconds: float = 600.0
    liteparse_auto_ocr: bool = True
    liteparse_output_format: str = "markdown"
    liteparse_dpi: float = 150.0
    liteparse_max_pages: int = 1000


# The collection a caller gets when they name none: the `--collection` default on
# every `rag-*` command, and the one the search and sync request bodies fall back to.
#
# It was `documents`, which is the tracking table's own name once the store prefixes
# it - so the documented first-run ingest, `rag-ingest ./docs/guide.pdf` with no
# `--collection`, aimed the quickstart at `rag_documents` and failed creating an
# index on a column that table does not have (#345). A name is now refused when the
# models declare its table, and a default that is refused is not a default, so this
# moved rather than the refusal being softened. `RAGSettings` carried a
# `collection_name` field spelling the same value once more; nothing read it, so it
# is gone rather than moved here.
#
# `tests/test_reserved_collection_names.py` asserts this never names a model table
# again, which is the only guard that survives somebody editing the line.
DEFAULT_COLLECTION_NAME = "default"


class RAGSettings(BaseModel):
    """RAG pipeline configuration."""

    allowed_extensions: list[DocumentExtensions] = Field(
        default_factory=lambda: list(DocumentExtensions)
    )

    chunk_size: int = 512
    chunk_overlap: int = 50
    chunking_strategy: str = "recursive"
    enable_hybrid_search: bool = False
    enable_ocr: bool = False

    embeddings_config: EmbeddingsConfig = Field(default_factory=EmbeddingsConfig)

    document_parser: DocumentParser = Field(default_factory=DocumentParser)
    pdf_parser: PdfParser = Field(default_factory=PdfParser)
    enable_image_description: bool = True
    image_description_model: str = ""
    gdrive_ingestion: bool = True
