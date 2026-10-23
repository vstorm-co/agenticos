"use client";

import {
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { ProviderIcon } from "@/components/vault/provider-icon";
import type { JsonSchema } from "@/types/agents";

/** A provider and the models a capability may choose on it - the server's catalog. */
export interface ProviderOffering {
  provider: string;
  name: string;
  models: { id: string; name: string; description: string }[];
}

/** What a binding will actually run with, which for an untouched one is not what it stores. */
export interface ResolvedOffering<P extends ProviderOffering> {
  /** The provider id the binding stores, or "" for an untouched binding. */
  stored: string;
  current: P | undefined;
  model: string;
  selected: P["models"][number] | undefined;
}

/**
 * Resolve the provider and model a binding will run with.
 *
 * `config: {}` is the normal shape of a capability somebody has only switched on,
 * and the server resolves both fields from the head of the same catalog through a
 * `default_factory` - which Pydantic does not emit as a JSON Schema default, so
 * nothing here could infer it. Showing two empty "Choose…" fields for a binding
 * that will run on the first provider's first model is the panel lying about what
 * it is configured to do. Resolved for display only: the config is written when
 * somebody picks, so the server keeps deciding the default.
 */
export function resolveOffering<P extends ProviderOffering>(
  providers: P[],
  config: Record<string, unknown>,
): ResolvedOffering<P> {
  const stored = typeof config.provider === "string" ? config.provider : "";
  const current =
    providers.find((entry) => entry.provider === stored) ??
    (stored === "" ? providers[0] : undefined);
  const storedModel = typeof config.model === "string" ? config.model : "";
  const model =
    current?.models.some((entry) => entry.id === storedModel) === true
      ? storedModel
      : (current?.models[0]?.id ?? "");
  const selected = current?.models.find((entry) => entry.id === model);
  return { stored, current, model, selected };
}

/** The copy around the two selects, already translated by the capability's panel. */
export interface ProviderModelCopy {
  provider: string;
  providerPlaceholder: string;
  providerDetail: string;
  model: string;
  modelPlaceholder: string;
  modelDetail: string;
  /** Said under the model select when the binding names a provider not offered. */
  unknownProvider: (provider: string) => string;
}

interface ProviderModelFieldsProps<P extends ProviderOffering> {
  idPrefix: string;
  providers: P[];
  resolved: ResolvedOffering<P>;
  copy: ProviderModelCopy;
  disabled?: boolean;
  onChange: (patch: { provider?: string; model: string }) => void;
}

/**
 * Whose model, and which one - two selects, because it is two decisions.
 *
 * Shared by every capability that makes media through a provider the author picks
 * (image generation, text to speech, video generation), so a person choosing a voice meets exactly
 * the controls they met choosing a painter. Both lists are the server's catalog.
 * Each model carries a sentence saying when to reach for it, which is the reason
 * the catalog is a file rather than an enum: a dropdown of ids is a decision made
 * by guessing.
 */
export function ProviderModelFields<P extends ProviderOffering>({
  idPrefix,
  providers,
  resolved,
  copy,
  disabled,
  onChange,
}: ProviderModelFieldsProps<P>) {
  const { stored, current, model, selected } = resolved;

  /** Switching provider re-points the model, because an id is not portable. */
  const chooseProvider = (next: string) => {
    const entry = providers.find((candidate) => candidate.provider === next);
    // The select only ever hands back a value from the list below, so the lookup
    // cannot miss; the `?.` is the type checker's price for that rather than a
    // fallback anybody reaches.
    onChange({ provider: next, model: entry?.models[0]?.id ?? "" });
  };

  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <div className="space-y-1.5">
        <Label htmlFor={`${idPrefix}-provider`}>{copy.provider}</Label>
        <Select
          value={current?.provider ?? ""}
          disabled={disabled || providers.length === 0}
          onValueChange={chooseProvider}
        >
          <SelectTrigger id={`${idPrefix}-provider`}>
            <SelectValue placeholder={copy.providerPlaceholder} />
          </SelectTrigger>
          <SelectContent>
            {providers.map((entry) => (
              <SelectItem key={entry.provider} value={entry.provider}>
                <span className="flex items-center gap-2">
                  <ProviderIcon provider={entry.provider} className="h-3.5 w-3.5" />
                  {entry.name}
                </span>
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <p className="text-muted-foreground text-xs">{copy.providerDetail}</p>
      </div>

      <div className="space-y-1.5">
        <Label htmlFor={`${idPrefix}-model`}>{copy.model}</Label>
        <Select
          value={model}
          disabled={disabled || current === undefined}
          onValueChange={(next) => onChange({ model: next })}
        >
          <SelectTrigger id={`${idPrefix}-model`}>
            {/* The trigger draws the name alone. Radix mirrors an item's
                `ItemText` into the closed trigger, and this item's is two
                lines - so the sentence saying when to reach for the model
                arrived inside a 36px-high field, laid out as a block in the
                middle of it. Explicit children keep the sentence in the list,
                which is the only place it means anything. */}
            <SelectValue placeholder={copy.modelPlaceholder}>
              <span className="truncate">{selected?.name ?? model}</span>
            </SelectValue>
          </SelectTrigger>
          <SelectContent>
            {(current?.models ?? []).map((entry) => (
              <SelectItem key={entry.id} value={entry.id}>
                <span className="flex flex-col gap-0.5">
                  <span>{entry.name}</span>
                  <span className="text-muted-foreground text-xs">{entry.description}</span>
                </span>
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <p className="text-muted-foreground text-xs">
          {current === undefined && stored !== "" ? copy.unknownProvider(stored) : copy.modelDetail}
        </p>
      </div>
    </div>
  );
}

/**
 * A schema with the fields a panel draws itself taken out.
 *
 * Subtracting rather than listing what to keep, the way the delegation panel does
 * it: a field added to the capability's config appears in the generated form on
 * its own.
 */
export function withoutFields(schema: JsonSchema, drawn: readonly string[]): JsonSchema {
  const properties = Object.fromEntries(
    Object.entries(schema.properties ?? {}).filter(([name]) => !drawn.includes(name)),
  );
  return { ...schema, properties };
}

/**
 * A binding's config with some settings taken out - for a setting whose default
 * is no value stored, or one that means nothing once the model changes.
 */
export function withoutConfig(
  config: Record<string, unknown>,
  names: readonly string[],
): Record<string, unknown> {
  return Object.fromEntries(Object.entries(config).filter(([name]) => !names.includes(name)));
}

/**
 * What publish refused about the fields a panel draws itself.
 *
 * The generated form shows a refusal beside its own field, and a hand-drawn
 * control has no such slot - so a refused model, voice or resolution was the
 * banner's "Invalid configuration" and nothing on the card (#2265). Listed under
 * the controls, in the order the panel draws them.
 */
export function DrawnFieldErrors({
  errors,
  fields,
}: {
  errors: Readonly<Record<string, string>>;
  fields: readonly string[];
}) {
  const refused = fields.filter((field) => errors[field] !== undefined);
  if (refused.length === 0) return null;
  return (
    <div className="space-y-1">
      {refused.map((field) => (
        <p key={field} className="text-destructive text-xs">
          {errors[field]}
        </p>
      ))}
    </div>
  );
}
