"use client";

import type { ReactNode } from "react";
import { useTranslations } from "next-intl";

import {
  DrawnFieldErrors,
  ProviderModelFields,
  withoutConfig,
} from "@/components/agents/provider-model-fields";
import {
  Input,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { SecretPicker } from "@/components/workflows/pickers/secret-picker";
import { useImageProviders, useVideoProviders } from "@/hooks/use-model-providers";
import { MediaCostEstimate } from "./media-cost-estimate";

const IMAGE_OPTIONS = ["quality", "size", "aspect_ratio", "background", "output_format"] as const;
const VIDEO_OPTIONS = ["resolution", "aspect_ratio", "seconds", "audio"] as const;
const MODEL_OPTIONS = [...new Set([...IMAGE_OPTIONS, ...VIDEO_OPTIONS])];

/** These fields are drawn here; bounds, filename and other settings remain schema-driven. */
export type MediaGenerationNode = "image.generate" | "video.generate";

export const MEDIA_GENERATION_FIELDS: Readonly<Record<MediaGenerationNode, readonly string[]>> = {
  "image.generate": ["provider", "model", "secret_id", ...IMAGE_OPTIONS],
  "video.generate": ["provider", "model", "secret_id", ...VIDEO_OPTIONS],
};

export function isMediaGenerationNode(id: string): id is MediaGenerationNode {
  return id === "image.generate" || id === "video.generate";
}

const OPTION_LABELS = {
  quality: "mediaQuality",
  size: "mediaSize",
  aspect_ratio: "mediaAspectRatio",
  background: "mediaBackground",
  output_format: "mediaOutputFormat",
  resolution: "mediaResolution",
  audio: "mediaAudio",
} as const;

interface Option {
  field: keyof typeof OPTION_LABELS;
  choices: string[];
  defaultValue: string | null;
}

interface MediaModel {
  id: string;
  name: string;
  description: string;
  referenceImage: boolean;
  pricingAsOf: string;
  options: Option[];
  defaults: Record<string, unknown>;
  duration?: { choosable: boolean; min: number; max: number; defaultValue: number | null };
  audioMode?: "always" | "optional" | "never";
}

interface MediaProvider {
  provider: string;
  name: string;
  models: MediaModel[];
}

interface MediaGenerationFieldsProps {
  nodeType: MediaGenerationNode;
  idPrefix: string;
  config: Record<string, unknown>;
  errors: ReadonlyMap<string, string>;
  disabled?: boolean;
  onChange: (config: Record<string, unknown>) => void;
  /** Keep an existing refused reference editable; hide a new unsupported reference binding. */
  children: (referenceAllowed: boolean | null) => ReactNode;
}

/** Fetch only the selected media family's catalog, never a provider or credential value. */
export function MediaGenerationFields(props: MediaGenerationFieldsProps) {
  return props.nodeType === "image.generate" ? (
    <ImageFields {...props} />
  ) : (
    <VideoFields {...props} />
  );
}

function ImageFields(props: MediaGenerationFieldsProps) {
  const { providers, isLoading, isError } = useImageProviders();
  const offered: MediaProvider[] = providers
    .map((provider) => ({
      ...provider,
      models: provider.models.flatMap((model): MediaModel[] => {
        const support = model.workflow;
        if (support == null) return [];
        const choices = {
          quality: support.qualities,
          size: support.sizes,
          aspect_ratio: support.aspect_ratios,
          background: support.backgrounds,
          output_format: support.output_formats,
        };
        return [
          {
            ...model,
            referenceImage: support.reference_image,
            pricingAsOf: support.pricing_as_of,
            defaults: Object.fromEntries(
              Object.entries(support.defaults).filter(([, value]) => value !== null),
            ),
            options: IMAGE_OPTIONS.filter((field) => choices[field].length > 0).map((field) => ({
              field,
              choices: choices[field],
              defaultValue: support.defaults[field],
            })),
          },
        ];
      }),
    }))
    .filter((provider) => provider.models.length > 0);
  return <MediaFields {...props} providers={offered} isLoading={isLoading} isError={isError} />;
}

function VideoFields(props: MediaGenerationFieldsProps) {
  const { providers, isLoading, isError } = useVideoProviders();
  const offered: MediaProvider[] = providers
    .map((provider) => ({
      ...provider,
      models: provider.models.flatMap((model): MediaModel[] => {
        const support = model.workflow;
        if (support == null) return [];
        const options: Option[] = [
          {
            field: "resolution",
            choices: model.resolutions,
            defaultValue: support.defaults.resolution,
          },
          {
            field: "aspect_ratio",
            choices: model.aspect_ratios,
            defaultValue: support.defaults.aspect_ratio,
          },
        ];
        if (model.audio === "optional")
          options.push({
            field: "audio",
            choices: ["true", "false"],
            defaultValue: String(support.defaults.audio),
          });
        return [
          {
            ...model,
            referenceImage: support.reference_image,
            pricingAsOf: support.pricing_as_of,
            defaults: Object.fromEntries(
              Object.entries(support.defaults).filter(([, value]) => value !== null),
            ),
            options,
            duration: {
              choosable: model.duration_choosable,
              min: model.min_seconds,
              max: model.max_seconds,
              defaultValue: support.defaults.seconds,
            },
            audioMode: model.audio,
          },
        ];
      }),
    }))
    .filter((provider) => provider.models.length > 0);
  return <MediaFields {...props} providers={offered} isLoading={isLoading} isError={isError} />;
}

function MediaFields({
  providers,
  isLoading,
  isError,
  nodeType,
  idPrefix,
  config,
  errors,
  disabled,
  onChange,
  children,
}: MediaGenerationFieldsProps & {
  providers: MediaProvider[];
  isLoading: boolean;
  isError: boolean;
}) {
  const t = useTranslations("workflows");
  const stored = typeof config.provider === "string" ? config.provider : "";
  const modelId = typeof config.model === "string" ? config.model : "";
  const current = providers.find((entry) => entry.provider === stored);
  const selected = current?.models.find((entry) => entry.id === modelId);
  const locked = disabled || isLoading || isError;

  function chooseOffering(patch: { provider?: string; model: string }) {
    if (locked) return;
    const nextProvider = patch.provider ?? stored;
    const next = providers
      .find((entry) => entry.provider === nextProvider)
      ?.models.find((entry) => entry.id === patch.model);
    if (next === undefined) return;
    const removed = nextProvider === stored ? MODEL_OPTIONS : [...MODEL_OPTIONS, "secret_id"];
    onChange({
      ...withoutConfig(config, removed),
      ...next.defaults,
      provider: nextProvider,
      model: patch.model,
    });
  }

  function setOption(field: string, value: unknown) {
    if (locked) return;
    const kept = withoutConfig(config, [field]);
    onChange(value === undefined ? kept : { ...kept, [field]: value });
  }

  function shown(option: Option): string {
    const value = config[option.field];
    return value === undefined || value === null ? (option.defaultValue ?? "") : String(value);
  }

  const optionLabel = (field: string, value: string) =>
    field === "audio" ? t(value === "true" ? "mediaAudioOn" : "mediaAudioOff") : value;
  const unavailable = !isLoading && !isError && modelId !== "" && selected === undefined;

  return (
    <div className="space-y-6">
      <ProviderModelFields
        idPrefix={idPrefix}
        providers={providers}
        resolved={{ stored, current, model: modelId, selected }}
        disabled={locked}
        onChange={chooseOffering}
        copy={{
          provider: t("mediaProvider"),
          providerPlaceholder: t("mediaProviderPlaceholder"),
          providerDetail: t("mediaProviderDetail"),
          model: t("mediaModel"),
          modelPlaceholder: t("mediaModelPlaceholder"),
          modelDetail: t("mediaModelDetail"),
          unknownProvider: (provider) => t("mediaUnknownProvider", { provider }),
        }}
      />
      {isLoading && <p className="text-muted-foreground text-xs">{t("mediaCatalogLoading")}</p>}
      {isError && <p className="text-destructive text-xs">{t("mediaCatalogError")}</p>}
      {!isLoading && !isError && providers.length === 0 && (
        <p className="text-muted-foreground text-xs">{t("mediaCatalogEmpty")}</p>
      )}
      {unavailable && (
        <p className="text-destructive text-xs">{t("mediaUnavailableModel", { model: modelId })}</p>
      )}
      <div className="space-y-2">
        <SecretPicker
          key={stored}
          label={
            current === undefined ? t("mediaKey") : t("mediaKeyFor", { provider: current.name })
          }
          value={typeof config.secret_id === "string" ? config.secret_id : null}
          kind="api_key"
          purpose={stored}
          usageScope="organization"
          disabled={locked || selected === undefined}
          error={errors.get("secret_id")}
          onChange={(value) => setOption("secret_id", value ?? undefined)}
        />
        <p className="text-muted-foreground text-xs">{t("mediaKeyDetail")}</p>
      </div>
      {selected !== undefined && (
        <>
          <div className="grid gap-4 sm:grid-cols-2">
            {selected.options.map((option) => (
              <div key={option.field} className="space-y-1.5" data-field={option.field}>
                <Label htmlFor={`${idPrefix}-${option.field}`}>
                  {t(OPTION_LABELS[option.field])}
                </Label>
                <Select
                  value={shown(option)}
                  disabled={locked}
                  onValueChange={(value) =>
                    setOption(option.field, option.field === "audio" ? value === "true" : value)
                  }
                >
                  <SelectTrigger id={`${idPrefix}-${option.field}`}>
                    <SelectValue>{optionLabel(option.field, shown(option))}</SelectValue>
                  </SelectTrigger>
                  <SelectContent>
                    {option.choices.map((value) => (
                      <SelectItem key={value} value={value}>
                        {optionLabel(option.field, value)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            ))}
            {selected.duration?.choosable && (
              <div className="space-y-1.5" data-field="seconds">
                <Label htmlFor={`${idPrefix}-seconds`}>{t("mediaSeconds")}</Label>
                <Input
                  id={`${idPrefix}-seconds`}
                  type="number"
                  min={selected.duration.min}
                  max={selected.duration.max}
                  step={1}
                  value={
                    typeof config.seconds === "number"
                      ? config.seconds
                      : (selected.duration.defaultValue ?? "")
                  }
                  disabled={locked}
                  onChange={(event) =>
                    setOption(
                      "seconds",
                      event.target.value === "" ? undefined : Number(event.target.value),
                    )
                  }
                />
              </div>
            )}
          </div>
          {selected.duration !== undefined && (
            <p className="text-muted-foreground text-xs">
              {t(selected.duration.choosable ? "mediaDurationRange" : "mediaDurationAutomatic", {
                min: selected.duration.min,
                max: selected.duration.max,
              })}
            </p>
          )}
          {selected.audioMode === "always" && (
            <p className="text-muted-foreground text-xs">{t("mediaAudioAlways")}</p>
          )}
          {selected.audioMode === "never" && (
            <p className="text-muted-foreground text-xs">{t("mediaAudioNever")}</p>
          )}
          <p className="text-muted-foreground text-xs">
            {t(selected.referenceImage ? "mediaReferenceSupported" : "mediaReferenceUnsupported")}
          </p>
          <p className="text-muted-foreground text-xs">
            {t("mediaPricingAsOf", { date: selected.pricingAsOf })}
          </p>
        </>
      )}
      <p className="text-muted-foreground text-xs">{t("mediaBudgetDetail")}</p>
      <DrawnFieldErrors
        errors={Object.fromEntries(errors)}
        fields={MEDIA_GENERATION_FIELDS[nodeType].filter((field) => field !== "secret_id")}
      />
      {children(isLoading || isError ? null : selected?.referenceImage === true)}
      {selected !== undefined && (
        <MediaCostEstimate
          request={{ kind: nodeType === "image.generate" ? "image" : "video", config }}
          disabled={locked}
        />
      )}
    </div>
  );
}
