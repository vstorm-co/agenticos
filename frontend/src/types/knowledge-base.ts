export type KBScope = "personal" | "org" | "app";

/**
 * Which parser reads the PDFs put into a collection.
 *
 * PDFs only: txt, md and docx go through built-in readers whatever this says.
 */
export type PdfParser = "pymupdf" | "llamaparse" | "liteparse";

/** LlamaParse's own quality/price ladder. Ignored by the other parsers. */
export type LlamaParseTier = "fast" | "cost_effective" | "agentic" | "agentic_plus";

/**
 * What LiteParse renders a page as. Ignored by the other parsers.
 *
 * `markdown` reconstructs headings, tables and lists from the spatial layout,
 * which is what the `markdown` chunking strategy splits on. `text` keeps the
 * grid, where a table stays aligned but carries no structure.
 */
export type LiteParseOutputFormat = "markdown" | "text";

/** How a parsed document is cut into the pieces that get embedded. */
export type ChunkingStrategy = "recursive" | "markdown" | "fixed";

/** Pydantic AI's reasoning ladder. A level a provider lacks maps to its closest. */
export type ThinkingEffort = "minimal" | "low" | "medium" | "high" | "xhigh";

/**
 * The model that turns pictures inside a document into searchable text.
 *
 * `temperature` and `thinking` are `null` when nothing was chosen, and that is
 * not a synonym for a value: an unset parameter is never sent, and reasoning
 * models reject `temperature` however it is spelled.
 */
export interface ImageDescriptionConfig {
  /** `null` uses the organization's default model profile. */
  model_profile_id: string | null;
  prompt: string;
  temperature: number | null;
  thinking: ThinkingEffort | null;
}

/**
 * How the documents put into one collection are parsed, chunked and described.
 *
 * Every field is required on the wire - the API answers a complete object and
 * both create and update replace it wholesale. The per-upload departure from it
 * is `IngestionOverride`, where every field is optional.
 */
export interface IngestionConfig {
  pdf_parser: PdfParser;
  ocr: boolean;
  llamaparse_tier: LlamaParseTier;
  /** The org vault key LlamaParse is billed to; null = the deployment's key. */
  llamaparse_secret_id?: string | null;
  /**
   * Whether LiteParse decides per document if OCR is worth running.
   *
   * Only consulted when `ocr` is on. OCR dominates the cost of a parse and most
   * documents are born digital, so leaving this on is the difference between
   * OCRing every page and OCRing the scans.
   */
  auto_ocr: boolean;
  /** Tesseract code - three letters, `+`-joined for several ("eng+pol"). */
  ocr_language: string;
  liteparse_output_format: LiteParseOutputFormat;
  liteparse_dpi: number;
  /** Pages LiteParse reads before it stops - what actually bounds the cost. */
  max_pages: number;
  parse_timeout_seconds: number;
  chunk_size: number;
  chunk_overlap: number;
  chunking_strategy: ChunkingStrategy;
  describe_images: boolean;
  image_description: ImageDescriptionConfig;
}

/**
 * One upload's departures from its collection's configuration.
 *
 * Sent as a JSON string in the multipart field `ingestion`, which is why it has
 * no schema of its own on the wire and is spelled as a partial here. An omitted
 * key inherits the collection's setting; a present one applies to this document
 * and is recorded on it.
 */
export type IngestionOverride = Partial<Omit<IngestionConfig, "image_description">> & {
  image_description?: Partial<ImageDescriptionConfig>;
};

export interface KnowledgeBase {
  id: string;
  organization_id: string | null;
  owner_user_id: string | null;
  name: string;
  description: string | null;
  scope: KBScope;
  collection_name: string;
  is_default: boolean;
  ingestion_config: IngestionConfig;
  /**
   * What this collection's vectors were built with, recorded once at creation.
   *
   * Read-only, and not an oversight: the store writes `embedding vector(N)` when
   * the collection is made, and two models of equal width write into different
   * spaces that search would go on comparing. It is on no create or update
   * schema, and sending it is silently ignored - so it is stated as fact here,
   * never offered as a control.
   */
  embedding_model: string;
  embedding_dim: number;
  /**
   * The reranker reordering this collection's search results, and the org vault
   * key it is billed to. Both null unless reranking is configured. Unlike the
   * embedding model this pair can be changed after creation - see
   * `UpdateRerankInput`.
   */
  rerank_model: string | null;
  rerank_secret_id: string | null;
  /**
   * Whose endpoint serves that model - a provider id from
   * `GET /rag/embedding-models`.
   *
   * Editable, unlike the model above, and the difference is the point: the same
   * model at the same width produces vectors in the same space wherever it is
   * served from, so moving a collection to another provider (a rotated key, an
   * organization's own account) leaves everything already indexed valid, while
   * moving it to another *model* would not.
   */
  embedding_provider: string;
  embedding_secret_id: string | null;
  created_at: string;
  updated_at: string | null;
  /**
   * What the collection holds. Answered by the listing only.
   *
   * Derived per request from the tracked-documents table, so the single-row
   * responses - create, read, update - leave all three at zero rather than
   * counting to restate what the caller just did. Read them off the list.
   *
   * `document_count` includes documents still parsing and documents that failed;
   * `indexed_count` is how many finished. The two disagreeing is the only place
   * a half-broken collection shows up in a listing.
   */
  document_count: number;
  indexed_count: number;
  chunk_count: number;
}

export interface KnowledgeBaseList {
  items: KnowledgeBase[];
  total: number;
}

export interface CreateKnowledgeBaseInput {
  name: string;
  description?: string;
  scope: KBScope;
  /**
   * Omit to inherit this deployment's defaults, which is what most collections
   * want. Present, it is taken whole - there is no merging with the defaults.
   */
  ingestion_config?: IngestionConfig;
  /**
   * Frozen at creation: the vector column is created at this model's width.
   * Omit for the deployment default.
   */
  embedding_model?: string;
  /** Whose endpoint serves it; omit for the deployment key's own provider. */
  embedding_provider?: string;
  /** The org vault key that pays for embeddings; omit for the deployment key. */
  embedding_secret_id?: string;
  /**
   * The reranker applied to search results. Reranking is on only when this and
   * `rerank_secret_id` are both sent; omit both to leave it off.
   */
  rerank_model?: string;
  /** The org vault key that pays for reranking - a `cohere`-purpose api_key. */
  rerank_secret_id?: string;
}

/**
 * Changing a collection's reranking after creation.
 *
 * The pair is read together on the backend: send both to turn reranking on or
 * change its key, both `null` to turn it off, and omit both to leave it be
 * (which is why they are `null`-able rather than merely optional - `null` is the
 * "off" signal, absence is "don't touch"). No other field changes here; name,
 * description and ingestion have their own paths.
 */
export interface UpdateRerankInput {
  rerank_model: string | null;
  rerank_secret_id: string | null;
}

/** What a collection's embeddings may be re-pointed at after the fact. */
export interface EmbeddingProviderInput {
  embedding_provider?: string;
  embedding_secret_id?: string;
  /**
   * Go back to the deployment's key.
   *
   * Its own flag because a null `embedding_secret_id` means "leave the key
   * alone" on a partial update, and both have to be sayable.
   */
  clear_embedding_secret?: boolean;
}

/** One provider a collection can embed through, from `GET /rag/embedding-models`. */
export interface EmbeddingProvider {
  provider: string;
  name: string;
  models: { model: string; dim: number }[];
  /** Whether this deployment's own key pays here. */
  deployment_key: boolean;
}

export interface EmbeddingModels {
  default: string;
  default_provider: string;
  providers: EmbeddingProvider[];
}

/** A single document tracked in a KB's underlying vector collection. */
export interface KBDocument {
  id: string;
  collection_name: string;
  filename: string;
  filetype: string | null;
  filesize: number | null;
  /**
   * `rag_documents.status`, as the worker wrote it - `processing`, `done` or
   * `error`. Read it through `ragStatus` in `@/lib/rag-status`.
   *
   * Not narrowed to those three, because the column is a free `String(20)` and
   * nothing constrains it to them. This used to claim `pending | completed |
   * failed`, three words the backend has never written, and the badge built on
   * that union drew every finished document as its raw token (#356).
   */
  status: string;
  error_message: string | null;
  vector_document_id: string | null;
  chunk_count: number;
  has_file: boolean;
  created_at: string;
  completed_at: string | null;
  /**
   * What actually read this document, rather than what the collection is
   * configured with today.
   *
   * Recorded at upload and never revised, which is the point: the collection's
   * configuration moves on, and comparing the two later would start calling
   * ordinary uploads departures. `null` on documents ingested before any of this
   * was recorded.
   */
  parser: string | null;
  image_description_model: string | null;
  embedding_model: string | null;
  /** Whether this one document was uploaded with a departure from the collection. */
  was_overridden: boolean;
}

export interface KBDocumentList {
  items: KBDocument[];
  total: number;
}

/**
 * One page of a document as the parser left it, chunk by chunk.
 *
 * Chunks arrive separately rather than joined because that is what was actually
 * indexed - adjacent chunks repeat their configured overlap, and a silent join
 * would present the duplication as the parser's mistake.
 */
export interface KBParsedPage {
  page_num: number;
  chunks: string[];
  /**
   * Whether anything on this page is worth embedding. An unreadable scan comes
   * back as an empty fenced code block - not whitespace - so this is the
   * server's answer, not something a `.trim()` on the client can reproduce.
   */
  has_text: boolean;
}

/** How a document parsed: the stored chunks, reconstructed in page order. */
export interface KBParsedContent {
  id: string;
  filename: string;
  parser: string | null;
  chunk_count: number;
  has_text: boolean;
  pages: KBParsedPage[];
}
