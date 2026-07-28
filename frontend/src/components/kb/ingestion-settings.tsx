"use client";

import type { ReactNode } from "react";

import { ModelProfilePicker } from "@/components/agents/model-profile-picker";
import {
  Input,
  Label,
  OptionalSetting,
  OptionalSlider,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Switch,
  Textarea,
} from "@/components/ui";
import { useModelProviders } from "@/hooks";
import {
  CHUNKING_STRATEGIES,
  DEFAULT_IMAGE_PROMPT,
  INGESTION_LIMITS,
  LITEPARSE_OUTPUT_FORMATS,
  LLAMAPARSE_TIERS,
  PDF_PARSERS,
  THINKING_EFFORTS,
  toNumber,
} from "@/lib/ingestion-config";
import type {
  ChunkingStrategy,
  ImageDescriptionConfig,
  IngestionConfig,
  LiteParseOutputFormat,
  LlamaParseTier,
  PdfParser,
  ThinkingEffort,
} from "@/types";

export interface IngestionSettingsProps {
  value: IngestionConfig;
  onChange: (value: IngestionConfig) => void;
  /**
   * Prefix for every control id.
   *
   * Two of these are on the knowledge base page at once - the collection's own
   * and the one a single upload departs from - and a duplicated id points every
   * second label at the first form's control.
   */
  idPrefix: string;
  /**
   * What the server refused, by the field it named. Keys are the config's own
   * field names, plus `ingestion_config` for a refusal about the object as a
   * whole, which is how the overlap rule arrives.
   */
  errors?: Readonly<Record<string, string>>;
  disabled?: boolean;
}

/**
 * How the documents put into one collection are read.
 *
 * The same form serves three places, because they are three views of one object:
 * a collection is created with it, edited with it, and one upload departs from
 * it. Writing the upload form separately is how the two would drift into
 * offering different parsers.
 *
 * Fields a parser ignores are not rendered - LlamaParse's tier means nothing to
 * PyMuPDF, and a control that changes nothing is worse than an absent one. The
 * values behind them are kept, so switching back finds the tier that was set.
 */
export function IngestionSettings({
  value,
  onChange,
  idPrefix,
  errors = {},
  disabled,
}: IngestionSettingsProps) {
  const id = (suffix: string) => `${idPrefix}-${suffix}`;
  const set = <K extends keyof IngestionConfig>(key: K, next: IngestionConfig[K]) =>
    onChange({ ...value, [key]: next });
  const setImage = <K extends keyof ImageDescriptionConfig>(
    key: K,
    next: ImageDescriptionConfig[K],
  ) => onChange({ ...value, image_description: { ...value.image_description, [key]: next } });

  const parser = PDF_PARSERS.find((choice) => choice.value === value.pdf_parser);

  return (
    <div className="space-y-6">
      {/* The refusal that names no single field: the chunk rule is about two of
          them, and pinning it to either would blame the one nobody edited. */}
      {errors.ingestion_config && (
        <p className="text-destructive text-xs">{errors.ingestion_config}</p>
      )}

      <Group label="Parsing">
        <OptionalSetting
          htmlFor={id("parser")}
          label="PDF parser"
          description={`${parser?.hint ?? ""} Text, Markdown and Word files use the built-in readers whichever is chosen.`}
          error={errors.pdf_parser}
          disabled={disabled}
        >
          <Select
            value={value.pdf_parser}
            disabled={disabled}
            onValueChange={(next) => set("pdf_parser", next as PdfParser)}
          >
            <SelectTrigger id={id("parser")} aria-invalid={errors.pdf_parser !== undefined}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {PDF_PARSERS.map((choice) => (
                <SelectItem key={choice.value} value={choice.value}>
                  {choice.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </OptionalSetting>

        <Toggle
          htmlFor={id("ocr")}
          label="Read scanned pages"
          description="A page that is a picture of text carries no text to extract. PyMuPDF hands such a page to the image model; LiteParse runs its own OCR."
          checked={value.ocr}
          disabled={disabled}
          onChange={(next) => set("ocr", next)}
        />

        {value.pdf_parser === "llamaparse" && (
          <OptionalSetting
            htmlFor={id("tier")}
            label="LlamaParse tier"
            description={
              LLAMAPARSE_TIERS.find((t) => t.value === value.llamaparse_tier)?.hint ?? ""
            }
            disabled={disabled}
          >
            <Select
              value={value.llamaparse_tier}
              disabled={disabled}
              onValueChange={(next) => set("llamaparse_tier", next as LlamaParseTier)}
            >
              <SelectTrigger id={id("tier")}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {LLAMAPARSE_TIERS.map((choice) => (
                  <SelectItem key={choice.value} value={choice.value}>
                    {choice.label}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </OptionalSetting>
        )}

        {value.pdf_parser === "liteparse" && value.ocr && (
          <Toggle
            htmlFor={id("auto-ocr")}
            label="Only OCR the pages that need it"
            description="LiteParse reads the text layer first and OCRs a page only when there is nothing there. OCR dominates the cost of a parse, and most documents are born digital. Turn this off to OCR every page regardless."
            checked={value.auto_ocr}
            disabled={disabled}
            onChange={(next) => set("auto_ocr", next)}
          />
        )}

        {value.pdf_parser === "liteparse" && (
          <div className="grid gap-4 sm:grid-cols-2">
            <OptionalSetting
              htmlFor={id("output-format")}
              label="Output"
              description={
                LITEPARSE_OUTPUT_FORMATS.find((f) => f.value === value.liteparse_output_format)
                  ?.hint ?? ""
              }
              disabled={disabled}
            >
              <Select
                value={value.liteparse_output_format}
                disabled={disabled}
                onValueChange={(next) =>
                  set("liteparse_output_format", next as LiteParseOutputFormat)
                }
              >
                <SelectTrigger id={id("output-format")}>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {LITEPARSE_OUTPUT_FORMATS.map((choice) => (
                    <SelectItem key={choice.value} value={choice.value}>
                      {choice.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </OptionalSetting>

            <OptionalSetting
              htmlFor={id("max-pages")}
              label="Maximum pages"
              description="Where LiteParse stops. This is what bounds the cost of one document - the timeout only bounds the wait."
              error={errors.max_pages}
              disabled={disabled}
            >
              <Input
                id={id("max-pages")}
                type="number"
                min={INGESTION_LIMITS.maxPages.min}
                max={INGESTION_LIMITS.maxPages.max}
                value={Number.isNaN(value.max_pages) ? "" : value.max_pages}
                disabled={disabled}
                aria-invalid={errors.max_pages !== undefined}
                aria-describedby={
                  errors.max_pages === undefined ? undefined : `${id("max-pages")}-error`
                }
                onChange={(event) => set("max_pages", toNumber(event.target.value))}
              />
            </OptionalSetting>

            <OptionalSetting
              htmlFor={id("dpi")}
              label="OCR resolution (DPI)"
              description="How finely a page is rendered before OCR reads it. Higher recovers faint scans and costs time."
              error={errors.liteparse_dpi}
              disabled={disabled}
            >
              <Input
                id={id("dpi")}
                type="number"
                min={INGESTION_LIMITS.liteparseDpi.min}
                max={INGESTION_LIMITS.liteparseDpi.max}
                value={Number.isNaN(value.liteparse_dpi) ? "" : value.liteparse_dpi}
                disabled={disabled}
                aria-invalid={errors.liteparse_dpi !== undefined}
                aria-describedby={
                  errors.liteparse_dpi === undefined ? undefined : `${id("dpi")}-error`
                }
                onChange={(event) => set("liteparse_dpi", toNumber(event.target.value))}
              />
            </OptionalSetting>

            <OptionalSetting
              htmlFor={id("ocr-language")}
              label="OCR language"
              description={`Tesseract codes, which are three letters: "eng", "pol", "deu". Join several with "+".`}
              error={errors.ocr_language}
              disabled={disabled}
            >
              <Input
                id={id("ocr-language")}
                value={value.ocr_language}
                disabled={disabled}
                spellCheck={false}
                placeholder="eng"
                aria-invalid={errors.ocr_language !== undefined}
                aria-describedby={
                  errors.ocr_language === undefined ? undefined : `${id("ocr-language")}-error`
                }
                onChange={(event) => set("ocr_language", event.target.value)}
              />
            </OptionalSetting>

            <OptionalSetting
              htmlFor={id("timeout")}
              label="Parse timeout (seconds)"
              description="How long LiteParse may spend on one document before it is abandoned."
              error={errors.parse_timeout_seconds}
              disabled={disabled}
            >
              <Input
                id={id("timeout")}
                type="number"
                min={1}
                max={INGESTION_LIMITS.parseTimeoutSeconds.max}
                value={Number.isNaN(value.parse_timeout_seconds) ? "" : value.parse_timeout_seconds}
                disabled={disabled}
                aria-invalid={errors.parse_timeout_seconds !== undefined}
                aria-describedby={
                  errors.parse_timeout_seconds === undefined ? undefined : `${id("timeout")}-error`
                }
                onChange={(event) => set("parse_timeout_seconds", toNumber(event.target.value))}
              />
            </OptionalSetting>
          </div>
        )}
      </Group>

      <Group label="Chunking">
        <div className="grid gap-4 sm:grid-cols-2">
          <OptionalSetting
            htmlFor={id("chunk-size")}
            label="Chunk size"
            description="Characters per embedded piece. Smaller pieces match a question more precisely; larger ones carry more of the surrounding argument."
            error={errors.chunk_size}
            disabled={disabled}
          >
            <Input
              id={id("chunk-size")}
              type="number"
              min={INGESTION_LIMITS.chunkSize.min}
              max={INGESTION_LIMITS.chunkSize.max}
              value={Number.isNaN(value.chunk_size) ? "" : value.chunk_size}
              disabled={disabled}
              aria-invalid={errors.chunk_size !== undefined}
              aria-describedby={
                errors.chunk_size === undefined ? undefined : `${id("chunk-size")}-error`
              }
              onChange={(event) => set("chunk_size", toNumber(event.target.value))}
            />
          </OptionalSetting>

          <OptionalSetting
            htmlFor={id("chunk-overlap")}
            label="Overlap"
            description="Characters each piece repeats from the one before it, so a sentence split across a boundary is still findable."
            error={errors.chunk_overlap}
            disabled={disabled}
          >
            <Input
              id={id("chunk-overlap")}
              type="number"
              min={INGESTION_LIMITS.chunkOverlap.min}
              max={INGESTION_LIMITS.chunkOverlap.max}
              value={Number.isNaN(value.chunk_overlap) ? "" : value.chunk_overlap}
              disabled={disabled}
              aria-invalid={errors.chunk_overlap !== undefined}
              aria-describedby={
                errors.chunk_overlap === undefined ? undefined : `${id("chunk-overlap")}-error`
              }
              onChange={(event) => set("chunk_overlap", toNumber(event.target.value))}
            />
          </OptionalSetting>
        </div>

        <OptionalSetting
          htmlFor={id("strategy")}
          label="Strategy"
          description={
            CHUNKING_STRATEGIES.find((c) => c.value === value.chunking_strategy)?.hint ?? ""
          }
          disabled={disabled}
        >
          <Select
            value={value.chunking_strategy}
            disabled={disabled}
            onValueChange={(next) => set("chunking_strategy", next as ChunkingStrategy)}
          >
            <SelectTrigger id={id("strategy")}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {CHUNKING_STRATEGIES.map((choice) => (
                <SelectItem key={choice.value} value={choice.value}>
                  {choice.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </OptionalSetting>
      </Group>

      <Group label="Images">
        <Toggle
          htmlFor={id("describe-images")}
          label="Describe images"
          description="Send the pictures inside a document to a model and index what it says about them. Needs a model profile with a working key, which is checked when this is saved."
          checked={value.describe_images}
          disabled={disabled}
          onChange={(next) => set("describe_images", next)}
        />

        {value.describe_images && (
          <div className="border-border space-y-6 rounded-lg border p-4">
            <ImageModelField
              value={value.image_description.model_profile_id}
              disabled={disabled}
              onChange={(next) => setImage("model_profile_id", next)}
            />

            <OptionalSetting
              htmlFor={id("prompt")}
              label="Prompt"
              description="What the model is asked to say about each image. What it answers is what a search matches, so name the things worth finding."
              error={errors.prompt}
              onReset={
                value.image_description.prompt === DEFAULT_IMAGE_PROMPT
                  ? undefined
                  : () => setImage("prompt", DEFAULT_IMAGE_PROMPT)
              }
              resetLabel="Use the standard prompt"
              disabled={disabled}
            >
              <Textarea
                id={id("prompt")}
                rows={3}
                value={value.image_description.prompt}
                disabled={disabled}
                maxLength={INGESTION_LIMITS.prompt.maxLength}
                aria-invalid={errors.prompt !== undefined}
                aria-describedby={errors.prompt === undefined ? undefined : `${id("prompt")}-error`}
                onChange={(event) => setImage("prompt", event.target.value)}
              />
            </OptionalSetting>

            <OptionalSlider
              id={id("temperature")}
              label="Temperature"
              description="How varied each description is. Left alone the parameter is not sent at all, which is not the same as sending zero - reasoning models reject it outright."
              max={INGESTION_LIMITS.temperature.max}
              value={value.image_description.temperature ?? undefined}
              resting={1}
              disabled={disabled}
              onChange={(next) => setImage("temperature", next ?? null)}
            />

            <OptionalSetting
              htmlFor={id("thinking")}
              label="Reasoning"
              description="How hard the model thinks before describing an image. A level a provider does not have maps to its closest one."
              disabled={disabled}
            >
              {/*
                Not a switch, and not a slider: the resting state is "no
                reasoning was asked for", which is a third answer rather than the
                bottom of the ladder - `minimal` still requests it.
              */}
              <Select
                value={value.image_description.thinking ?? NOT_REQUESTED}
                disabled={disabled}
                onValueChange={(next) =>
                  setImage("thinking", next === NOT_REQUESTED ? null : (next as ThinkingEffort))
                }
              >
                <SelectTrigger id={id("thinking")}>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={NOT_REQUESTED}>Not requested</SelectItem>
                  {THINKING_EFFORTS.map((effort) => (
                    <SelectItem key={effort} value={effort}>
                      {effort}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </OptionalSetting>
          </div>
        )}
      </Group>
    </div>
  );
}

/**
 * The select's word for "no reasoning was asked for".
 *
 * A Radix item cannot carry an empty value, and `null` is not a string, so the
 * absent state needs a name of its own on the way through the control.
 */
const NOT_REQUESTED = "not-requested";

/**
 * Which of the organization's models reads the images.
 *
 * Its own component so the vault is only read where something on screen can use
 * it - the same reason the Builder's secret picker reads it itself. `/providers/
 * model-profiles` is not a request every collection form should be making.
 */
function ImageModelField({
  value,
  onChange,
  disabled,
}: {
  value: string | null;
  onChange: (profileId: string | null) => void;
  disabled?: boolean;
}) {
  const { profiles } = useModelProviders();

  return (
    <div className="space-y-2">
      <Label htmlFor="image-description-model">Model</Label>
      {/* The picker is a radiogroup rather than a labelled control, so the label
          above names the group and this id exists for it to point at. */}
      <div id="image-description-model">
        <ModelProfilePicker
          profiles={profiles}
          value={value}
          onChange={onChange}
          disabled={disabled}
        />
      </div>
    </div>
  );
}

/** A named run of related settings. */
function Group({ label, children }: { label: string; children: ReactNode }) {
  return (
    <section role="group" aria-label={label} className="space-y-4">
      <p className="text-muted-foreground text-xs font-medium tracking-wide uppercase">{label}</p>
      {children}
    </section>
  );
}

/** A yes/no setting, laid out the way the Builder lays its reasoning switch out. */
function Toggle({
  htmlFor,
  label,
  description,
  checked,
  onChange,
  disabled,
}: {
  htmlFor: string;
  label: string;
  description: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
  disabled?: boolean;
}) {
  return (
    <div className="flex items-start justify-between gap-4">
      <div className="min-w-0">
        <Label htmlFor={htmlFor}>{label}</Label>
        <p className="text-muted-foreground mt-1 text-xs">{description}</p>
      </div>
      <Switch
        id={htmlFor}
        checked={checked}
        disabled={disabled}
        onCheckedChange={onChange}
        aria-label={label}
      />
    </div>
  );
}
