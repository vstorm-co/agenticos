"use client";

import { CapabilityDetail } from "@/components/agents/capability-settings";
import { useCapabilityFieldCopy } from "@/components/agents/capability-field-copy";
import {
  ProviderModelFields,
  resolveOffering,
  withoutFields,
} from "@/components/agents/provider-model-fields";
import { SchemaForm } from "@/components/agents/schema-form";
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
import type { FieldProblem } from "@/lib/api-error";
import type { CapabilityBindingSpec, CapabilityCatalogEntry } from "@/types/agents";
import { useTranslations } from "next-intl";

/** The fields this panel draws itself; the rest is the generated form. */
const HAND_ROLLED = ["provider", "model", "resolution", "aspect_ratio"];

/** What a model decides for itself, which means nothing on another model. */
const MODEL_SPECIFIC = ["resolution", "aspect_ratio", "seconds", "max_seconds", "audio"];

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

  /** A resolution, a length or a shape chosen for one model means nothing on another. */
  const chooseOffering = (patch: { provider?: string; model: string }) => {
    const kept = Object.fromEntries(
      Object.entries(binding.config).filter(([name]) => !MODEL_SPECIFIC.includes(name)),
    );
    onChange({ ...binding, config: { ...kept, ...patch } });
  };

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
            <Select
              value={shown("resolution", model.resolutions)}
              disabled={disabled}
              onValueChange={(next) => setConfig({ resolution: next })}
            >
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
            <p className="text-muted-foreground text-xs">
              {model.duration_choosable
                ? t("videoLengthRange", { min: model.min_seconds, max: model.max_seconds })
                : t("videoLengthDecided", { min: model.min_seconds, max: model.max_seconds })}
            </p>
          </div>
        </div>
      )}

      {isError && <p className="text-destructive text-xs">{t("videoProvidersUnavailable")}</p>}
      {isLoading && <p className="text-muted-foreground text-xs">{t("videoProvidersLoading")}</p>}

      {definition.config_schema && (
        <SchemaForm
          idPrefix={binding.id}
          schema={withoutFields(definition.config_schema, HAND_ROLLED)}
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
      // The controls above *are* this capability's configuration, the generated
      // fields included: drawing the form again would double every field.
      hideConfigForm
    />
  );
}
