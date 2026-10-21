"use client";

import { CapabilityDetail } from "@/components/agents/capability-settings";
import { useCapabilityFieldCopy } from "@/components/agents/capability-field-copy";
import {
  DrawnFieldErrors,
  ProviderModelFields,
  resolveOffering,
  withoutConfig,
  withoutFields,
} from "@/components/agents/provider-model-fields";
import { SchemaForm } from "@/components/agents/schema-form";
import { VideoMaxResolutionSelect } from "@/components/agents/video-max-resolution-select";
import {
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { useVideoProviders } from "@/hooks/use-model-providers";
import { capabilityConfigErrors } from "@/lib/agent-spec";
import { resolutionLines } from "@/lib/video-resolutions";
import type { FieldProblem } from "@/lib/api-error";
import type { CapabilityBindingSpec, CapabilityCatalogEntry } from "@/types/agents";
import { useTranslations } from "next-intl";

/** The fields this panel draws itself; the rest is the generated form. */
const HAND_ROLLED = ["provider", "model", "resolution", "max_resolution", "aspect_ratio", "audio"];

/** What a model that decides its own length would ignore, so it is not offered. */
const LENGTH_FIELDS = ["seconds", "max_seconds"];

/** The sound setting's three states, `default` being no value stored, and their copy. */
const AUDIO_CHOICES = {
  default: "videoAudioDefault",
  on: "videoAudioOn",
  off: "videoAudioOff",
} as const;

/** What a model decides for itself, which means nothing on another model. */
const MODEL_SPECIFIC = [
  "resolution",
  "max_resolution",
  "aspect_ratio",
  "seconds",
  "max_seconds",
  "audio",
];

interface VideoGenerationSectionProps {
  definition: CapabilityCatalogEntry | undefined;
  binding: CapabilityBindingSpec;
  onChange: (binding: CapabilityBindingSpec) => void;
  onToggleEnabled?: () => void;
  /** Whether the caller may edit the spec at all - see `CapabilityDetail`. */
  readOnly?: boolean;
  disabled?: boolean;
  configProblems?: readonly FieldProblem[];
}

/**
 * Whose model makes the clip, which one, and at what resolution and shape - the
 * image panel's two selects plus two the chosen model fills in.
 *
 * The resolutions and aspect ratios are the chosen model's own, from the catalog,
 * because the providers differ on every one: offering 4K for a model that renders
 * 720p is a choice that fails the first time the agent uses it. Length, sound and
 * the time limit are the generated form beneath.
 */
export function VideoGenerationSection({
  definition,
  binding,
  onChange,
  onToggleEnabled,
  readOnly,
  disabled,
  configProblems,
}: VideoGenerationSectionProps) {
  const t = useTranslations("agents");
  const { providers, isLoading, isError } = useVideoProviders();
  const configErrors = capabilityConfigErrors(configProblems ?? [], binding.id);
  const copyFor = useCapabilityFieldCopy(binding.id);

  if (!definition) return null;

  const resolved = resolveOffering(providers, binding.config);
  const model = resolved.selected;

  /** A stored value the model renders, or the model's first - what will run. */
  const shown = (field: string, offered: string[]) => {
    const stored = binding.config[field];
    return typeof stored === "string" && offered.includes(stored) ? stored : (offered[0] ?? "");
  };

  const setConfig = (patch: Record<string, unknown>) =>
    onChange({ ...binding, config: { ...binding.config, ...patch } });

  const usual = model === undefined ? "" : shown("resolution", model.resolutions);

  /** A usual resolution above the ceiling would be one the agent may not ask for. */
  const chooseResolution = (next: string) => {
    const ceiling = binding.config.max_resolution;
    const stale = typeof ceiling === "string" && resolutionLines(ceiling) < resolutionLines(next);
    const kept = stale ? withoutConfig(binding.config, ["max_resolution"]) : binding.config;
    onChange({ ...binding, config: { ...kept, resolution: next } });
  };

  /** A resolution, a length or a shape chosen for one model means nothing on another. */
  const chooseOffering = (patch: { provider?: string; model: string }) => {
    // A key is the provider's: kept across a switch it would be sent to the next
    // one, since publish checks only that it is an API key.
    const secret_id = patch.provider === undefined ? binding.secret_id : null;
    onChange({
      ...binding,
      secret_id,
      config: { ...withoutConfig(binding.config, MODEL_SPECIFIC), ...patch },
    });
  };

  // Everything the generated form below does not show - including the lengths a
  // model that decides its own leaves out - so a refusal of any of them is said.
  const drawn =
    model?.duration_choosable === false ? [...HAND_ROLLED, ...LENGTH_FIELDS] : HAND_ROLLED;

  const controls = (
    <div className="space-y-4">
      <ProviderModelFields
        idPrefix="video"
        providers={providers}
        resolved={resolved}
        disabled={disabled}
        onChange={chooseOffering}
        copy={{
          provider: t("videoProvider"),
          providerPlaceholder: t("videoProviderPlaceholder"),
          providerDetail: t("videoProviderDetail"),
          model: t("videoModel"),
          modelPlaceholder: t("videoModelPlaceholder"),
          modelDetail: t("videoModelDetail"),
          unknownProvider: (provider) => t("videoModelUnknownProvider", { provider }),
        }}
      />

      {model !== undefined && (
        <div className="grid gap-4 sm:grid-cols-2">
          <div className="space-y-1.5">
            <Label htmlFor="video-resolution">{t("videoResolution")}</Label>
            <Select value={usual} disabled={disabled} onValueChange={chooseResolution}>
              <SelectTrigger id="video-resolution">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {model.resolutions.map((entry) => (
                  <SelectItem key={entry} value={entry}>
                    {entry}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="text-muted-foreground text-xs">{t("videoResolutionDetail")}</p>
          </div>

          <div className="space-y-1.5">
            <Label htmlFor="video-aspect-ratio">{t("videoAspectRatio")}</Label>
            <Select
              value={shown("aspect_ratio", model.aspect_ratios)}
              disabled={disabled}
              onValueChange={(next) => setConfig({ aspect_ratio: next })}
            >
              <SelectTrigger id="video-aspect-ratio">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {model.aspect_ratios.map((entry) => (
                  <SelectItem key={entry} value={entry}>
                    {entry}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="text-muted-foreground text-xs">{t("videoAspectRatioDetail")}</p>
          </div>
        </div>
      )}

      {model !== undefined && (
        <VideoMaxResolutionSelect
          resolutions={model.resolutions}
          usual={usual}
          value={binding.config.max_resolution}
          disabled={disabled}
          onChange={(ceiling) => {
            const rest = withoutConfig(binding.config, ["max_resolution"]);
            onChange({
              ...binding,
              config: ceiling === null ? rest : { ...rest, max_resolution: ceiling },
            });
          }}
        />
      )}

      {model !== undefined && model.audio === "optional" && (
        <div className="space-y-1.5">
          <Label htmlFor="video-audio">{t("videoAudio")}</Label>
          <Select
            value={
              binding.config.audio === true
                ? "on"
                : binding.config.audio === false
                  ? "off"
                  : "default"
            }
            disabled={disabled}
            onValueChange={(next) => {
              const rest = withoutConfig(binding.config, ["audio"]);
              onChange({
                ...binding,
                config: next === "default" ? rest : { ...rest, audio: next === "on" },
              });
            }}
          >
            <SelectTrigger id="video-audio">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {Object.entries(AUDIO_CHOICES).map(([choice, label]) => (
                <SelectItem key={choice} value={choice}>
                  {t(label)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <p className="text-muted-foreground text-xs">{t("videoAudioDetail")}</p>
        </div>
      )}

      {model !== undefined && (
        <p className="text-muted-foreground text-xs">
          {model.duration_choosable
            ? t("videoLengthRange", { min: model.min_seconds, max: model.max_seconds })
            : t("videoLengthDecided", { min: model.min_seconds, max: model.max_seconds })}
        </p>
      )}

      <DrawnFieldErrors errors={configErrors} fields={drawn} />

      {isError && <p className="text-destructive text-xs">{t("videoProvidersUnavailable")}</p>}
      {isLoading && <p className="text-muted-foreground text-xs">{t("videoProvidersLoading")}</p>}

      {definition.config_schema && (
        <SchemaForm
          idPrefix={binding.id}
          schema={withoutFields(definition.config_schema, drawn)}
          value={binding.config}
          disabled={disabled}
          errors={configErrors}
          copyFor={copyFor}
          onChange={(config) => onChange({ ...binding, config })}
        />
      )}
    </div>
  );

  return (
    <CapabilityDetail
      binding={binding}
      definition={definition}
      onChange={onChange}
      onToggleEnabled={onToggleEnabled}
      readOnly={readOnly}
      disabled={disabled}
      configProblems={configProblems}
      settingsExtra={controls}
      resolvedConfig={
        resolved.current === undefined ? undefined : { provider: resolved.current.provider }
      }
      // The controls above *are* this capability's configuration, the generated
      // fields included: drawing the form again would double every field.
      hideConfigForm
    />
  );
}
