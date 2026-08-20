/**
 * The ingestion contract as the browser needs it: the options that exist, the
 * bounds the API enforces, and the two questions a form has to answer before it
 * sends anything - "is this valid" and "did anybody actually change it".
 *
 * The vocabulary is duplicated from the backend rather than fetched, because
 * there is no endpoint that publishes it: `IngestionConfig` is a field of the
 * KB schemas, not a capability with a `config_schema`. What that costs is one
 * place to update when a parser is added; what it buys is labels that say what
 * a parser is *for*, which a generated form could not.
 */

import { FileText, ScanText } from "lucide-react";
import type { ComponentType } from "react";

import { brandMark } from "@/components/icons/brand-icon";

import type { Translate } from "@/lib/agent-step-captions";
import type {
  ChunkingStrategy,
  ImageDescriptionConfig,
  IngestionConfig,
  IngestionOverride,
  LiteParseOutputFormat,
  LlamaParseTier,
  PdfParser,
  ThinkingEffort,
} from "@/types";

/**
 * What the model is asked about each image when nobody has said otherwise.
 *
 * i18n-exempt: a prompt, not copy. It is a field value posted to the API and stored on
 * the collection, so what matters is the sentence the model was asked - not the locale
 * of whoever last opened the editor.
 */
export const DEFAULT_IMAGE_PROMPT =
  // i18n-exempt: see above.
  "Describe this image in detail. Focus on any text, data, charts, diagrams, " +
  "or visual information that would be useful for document search and retrieval. " +
  // i18n-exempt: see above.
  "Be concise but comprehensive.";

/**
 * The defaults a collection gets when nobody chooses.
 *
 * These *are* the API's defaults now. They used to be only an approximation of
 * them: the API filled a missing object from environment variables an operator
 * could have set differently, so posting these would silently overrule a
 * deployment's own settings. Those variables are gone - how a collection parses
 * is a per-collection choice and the field defaults are the only defaults - so
 * this and the server agree by construction.
 *
 * Still a starting point for an editor somebody deliberately opened rather than
 * something to post on their behalf: what a collection actually got is on the
 * collection, and is what every read-out here is driven from.
 */
export const DEFAULT_INGESTION_CONFIG: IngestionConfig = {
  pdf_parser: "pymupdf",
  ocr: false,
  llamaparse_tier: "agentic",
  llamaparse_secret_id: null,
  auto_ocr: true,
  ocr_language: "eng",
  liteparse_output_format: "markdown",
  liteparse_dpi: 150,
  max_pages: 1000,
  parse_timeout_seconds: 600,
  chunk_size: 512,
  chunk_overlap: 50,
  chunking_strategy: "recursive",
  describe_images: false,
  image_description: {
    model_profile_id: null,
    prompt: DEFAULT_IMAGE_PROMPT,
    temperature: null,
    thinking: null,
  },
};

/**
 * One option in a menu, as keys under `kb`.
 *
 * Keys rather than words for the usual reason - a module constant cannot call a
 * translator - and *both* fields, including the labels that are product names. Keying
 * half a table of four is what leaves the next reader guessing which half (#446).
 */
interface Choice<T extends string> {
  readonly value: T;
  readonly labelKey: string;
  /** The one sentence that decides whether somebody picks this. */
  readonly hintKey: string;
  /**
   * The mark drawn beside the label, where the choice has one.
   *
   * A component rather than a name, so a brand and a lucide icon can sit in the
   * same table: `brandMark("llamaparse")` builds one from the generated path
   * data, and the two parsers with no public brand take a lucide icon. Only one
   * of the three is a product, and pretending otherwise is how a menu ends up
   * with one logo and two blanks (#940).
   *
   * Optional because most choices here are settings rather than products - an
   * output format has nothing to draw.
   */
  readonly Icon?: ComponentType<{ className?: string }>;
}

export const PDF_PARSERS: readonly Choice<PdfParser>[] = [
  {
    value: "pymupdf",
    labelKey: "parserPymupdf",
    hintKey: "parserPymupdfHint",
    // A library, not a product with a mark. `FileText` says "reads the text
    // that is already in the file", which is what it does.
    Icon: FileText,
  },
  {
    value: "llamaparse",
    labelKey: "parserLlamaparse",
    hintKey: "parserLlamaparseHint",
    // The only one of the three with a brand, generated from LlamaIndex's own
    // mark by `bun run gen:brand-icons` - never a hand-authored path (#156).
    Icon: brandMark("llamaparse"),
  },
  {
    value: "liteparse",
    labelKey: "parserLiteparse",
    hintKey: "parserLiteparseHint",
    // Also no public mark. `ScanText` for the one that looks at the page rather
    // than at the text layer.
    Icon: ScanText,
  },
];

export const LITEPARSE_OUTPUT_FORMATS: readonly Choice<LiteParseOutputFormat>[] = [
  {
    value: "markdown",
    labelKey: "formatMarkdown",
    hintKey: "formatMarkdownHint",
  },
  {
    value: "text",
    labelKey: "formatText",
    hintKey: "formatTextHint",
  },
];

export const LLAMAPARSE_TIERS: readonly Choice<LlamaParseTier>[] = [
  { value: "fast", labelKey: "tierFast", hintKey: "tierFastHint" },
  { value: "cost_effective", labelKey: "tierCostEffective", hintKey: "tierCostEffectiveHint" },
  { value: "agentic", labelKey: "tierAgentic", hintKey: "tierAgenticHint" },
  { value: "agentic_plus", labelKey: "tierAgenticPlus", hintKey: "tierAgenticPlusHint" },
];

export const CHUNKING_STRATEGIES: readonly Choice<ChunkingStrategy>[] = [
  {
    value: "recursive",
    labelKey: "chunkingRecursive",
    hintKey: "chunkingRecursiveHint",
  },
  {
    value: "markdown",
    labelKey: "chunkingMarkdown",
    hintKey: "chunkingMarkdownHint",
  },
  { value: "fixed", labelKey: "chunkingFixed", hintKey: "chunkingFixedHint" },
];

/** In the order the ladder climbs, which is the order they belong in a menu. */
export const THINKING_EFFORTS: readonly ThinkingEffort[] = [
  "minimal",
  "low",
  "medium",
  "high",
  "xhigh",
];

/**
 * The bounds the API enforces, restated so a form can refuse before a round trip.
 *
 * Kept beside the validator that reads them rather than inlined into markup: a
 * `min` attribute is a hint a keyboard can walk past, and the same numbers have
 * to appear in the message that explains the refusal.
 */
export const INGESTION_LIMITS = {
  chunkSize: { min: 64, max: 8192 },
  chunkOverlap: { min: 0, max: 4096 },
  /** Exclusive at the bottom: the API takes `0 < x <= 3600`. */
  parseTimeoutSeconds: { max: 3600 },
  liteparseDpi: { min: 72, max: 600 },
  maxPages: { min: 1, max: 10000 },
  prompt: { maxLength: 4000 },
  temperature: { min: 0, max: 2 },
} as const;

/**
 * Tesseract language codes, which are three letters and not the two-letter ISO
 * codes used for UI locales - "eng", not "en". Several are joined with `+`.
 *
 * The same expression the API enforces. Worth refusing here rather than on a
 * round trip: "pl" reads as a plausible answer and is the one Tesseract has no
 * pack for, so the parse would succeed and return nothing.
 */
const OCR_LANGUAGE_PATTERN = /^[a-z]{3}(\+[a-z]{3})*$/;

/**
 * The names `IngestionSettings` shows a refusal under, for `submitFailure`.
 *
 * They are the server's own field names, which is what makes the routing work:
 * a problem reported about `ingestion_config.chunk_size` is matched by its leaf.
 * `ingestion_config` itself is here for the one rule that is about two fields at
 * once - an overlap that does not fit inside a chunk - which the server
 * attributes to the object rather than to either of them.
 *
 * `model_profile_id` is deliberately absent. The server refuses an unusable
 * profile with a message that names the profile and no field at all, so there is
 * nothing to route; it reaches the person as a toast carrying that sentence,
 * and the picker badges a keyless profile before they ever submit.
 */
export const INGESTION_FORM_FIELDS: readonly string[] = [
  "ingestion_config",
  "pdf_parser",
  "ocr_language",
  "parse_timeout_seconds",
  "liteparse_dpi",
  "max_pages",
  "chunk_size",
  "chunk_overlap",
  "prompt",
];

/**
 * Everything this configuration would be refused for, keyed by the field to say
 * it under. Empty when the API would accept it.
 *
 * This is not a substitute for the server's answer - `describe_images` needs a
 * model profile it can resolve, which only the server knows - and nothing here
 * is allowed to hide one. It covers the refusals whose whole input is on screen,
 * so that typing an overlap larger than a chunk is answered where it is typed
 * rather than after a submit that discards the rest of the form.
 */
export function ingestionProblems(
  config: IngestionConfig,
  t: Translate,
): Readonly<Record<string, string>> {
  const problems: Record<string, string> = {};
  const { chunkSize, chunkOverlap, parseTimeoutSeconds, liteparseDpi, maxPages, prompt } =
    INGESTION_LIMITS;

  if (!isWhole(config.chunk_size, chunkSize.min, chunkSize.max)) {
    problems.chunk_size = t("problemWholeBetween", { min: chunkSize.min, max: chunkSize.max });
  }
  if (!isWhole(config.chunk_overlap, chunkOverlap.min, chunkOverlap.max)) {
    problems.chunk_overlap = t("problemWholeBetween", {
      min: chunkOverlap.min,
      max: chunkOverlap.max,
    });
  } else if (config.chunk_overlap >= config.chunk_size) {
    // The server's own rule, said in the same breath: an overlap that reaches
    // the end of a chunk means every chunk is the previous one.
    problems.chunk_overlap = t("problemOverlapTooLarge", { size: config.chunk_size });
  }
  if (
    !Number.isFinite(config.parse_timeout_seconds) ||
    config.parse_timeout_seconds <= 0 ||
    config.parse_timeout_seconds > parseTimeoutSeconds.max
  ) {
    problems.parse_timeout_seconds = t("problemTimeoutRange", { max: parseTimeoutSeconds.max });
  }
  if (!OCR_LANGUAGE_PATTERN.test(config.ocr_language.trim())) {
    problems.ocr_language = t("problemOcrLanguage");
  }
  if (!isWhole(config.liteparse_dpi, liteparseDpi.min, liteparseDpi.max)) {
    problems.liteparse_dpi = t("problemWholeBetween", {
      min: liteparseDpi.min,
      max: liteparseDpi.max,
    });
  }
  if (!isWhole(config.max_pages, maxPages.min, maxPages.max)) {
    problems.max_pages = t("problemWholeBetween", { min: maxPages.min, max: maxPages.max });
  }
  const text = config.image_description.prompt;
  if (text.length === 0 || text.length > prompt.maxLength) {
    problems.prompt = t("problemPromptLength", { max: prompt.maxLength });
  }
  return problems;
}

function isWhole(value: number, min: number, max: number): boolean {
  return Number.isInteger(value) && value >= min && value <= max;
}

/**
 * Read a number field back, keeping "nothing typed" out of the model.
 *
 * `Number("")` is 0, which for a chunk size is both a valid-looking number and a
 * value the API refuses - so an emptied box would silently become a refusal
 * about zero rather than a box somebody is halfway through editing. NaN stays
 * NaN and `ingestionProblems` names it.
 */
export function toNumber(raw: string): number {
  return raw.trim() === "" ? Number.NaN : Number(raw);
}

/** Whether two configurations say the same thing. */
export function sameIngestion(a: IngestionConfig, b: IngestionConfig): boolean {
  return ingestionKeys().every((key) => {
    if (key === "image_description") return sameImageDescription(a[key], b[key]);
    return a[key] === b[key];
  });
}

function sameImageDescription(a: ImageDescriptionConfig, b: ImageDescriptionConfig): boolean {
  return (
    a.model_profile_id === b.model_profile_id &&
    a.prompt === b.prompt &&
    a.temperature === b.temperature &&
    a.thinking === b.thinking
  );
}

/**
 * What `edited` says that `base` does not, in the shape the upload form field
 * takes.
 *
 * Only the keys that differ, because that is what the API means by an override:
 * an omitted key inherits, and a key sent with the collection's own value would
 * be recorded as a departure and mark the document overridden for no reason.
 */
export function ingestionOverride(
  base: IngestionConfig,
  edited: IngestionConfig,
): IngestionOverride {
  const override: IngestionOverride = {};
  for (const key of ingestionKeys()) {
    if (key === "image_description") continue;
    if (edited[key] !== base[key]) assign(override, key, edited[key]);
  }

  const images = imageDescriptionOverride(base.image_description, edited.image_description);
  if (images !== null) override.image_description = images;
  return override;
}

function imageDescriptionOverride(
  base: ImageDescriptionConfig,
  edited: ImageDescriptionConfig,
): Partial<ImageDescriptionConfig> | null {
  const override: Partial<ImageDescriptionConfig> = {};
  if (edited.model_profile_id !== base.model_profile_id) {
    override.model_profile_id = edited.model_profile_id;
  }
  if (edited.prompt !== base.prompt) override.prompt = edited.prompt;
  if (edited.temperature !== base.temperature) override.temperature = edited.temperature;
  if (edited.thinking !== base.thinking) override.thinking = edited.thinking;
  return Object.keys(override).length === 0 ? null : override;
}

/** How many things this upload does differently, for a form that has to say so. */
export function overrideSize(override: IngestionOverride): number {
  const { image_description: images, ...rest } = override;
  return Object.keys(rest).length + (images === undefined ? 0 : Object.keys(images).length);
}

/**
 * Copy one field across without widening it to the union of every field's type.
 *
 * `override[key] = edited[key]` does not typecheck: TypeScript resolves the
 * index and the value independently, so it sees `number | boolean | …` being
 * assigned to `number`. The generic ties them to the same `K`.
 */
function assign<K extends Exclude<keyof IngestionConfig, "image_description">>(
  override: IngestionOverride,
  key: K,
  value: IngestionConfig[K],
): void {
  override[key] = value;
}

/** Every field of the configuration, exhaustively - adding one breaks the build. */
function ingestionKeys(): (keyof IngestionConfig)[] {
  return Object.keys(DEFAULT_INGESTION_CONFIG) as (keyof IngestionConfig)[];
}

/** A choice's hint, or nothing for one this build does not know. */
export function hintOf<T extends string>(
  choices: readonly Choice<T>[],
  value: string,
  t: Translate,
): string {
  const key = choices.find((choice) => choice.value === value)?.hintKey;
  return key === undefined ? "" : t(key);
}

/** A choice's label, or the raw value for one this build does not know. */
export function labelOf<T extends string>(
  choices: readonly Choice<T>[],
  value: string,
  t: Translate,
): string {
  const key = choices.find((choice) => choice.value === value)?.labelKey;
  return key === undefined ? value : t(key);
}
