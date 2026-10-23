"use client";

import { CapabilityDetail } from "@/components/agents/capability-settings";
import { useCapabilityFieldCopy } from "@/components/agents/capability-field-copy";
import { SchemaForm } from "@/components/agents/schema-form";
import {
  ProviderModelFields,
  resolveOffering,
  withoutFields,
} from "@/components/agents/provider-model-fields";
import { useImageProviders } from "@/hooks/use-model-providers";
import { capabilityConfigErrors } from "@/lib/agent-spec";
import type { FieldProblem } from "@/lib/api-error";
import type { CapabilityBindingSpec, CapabilityCatalogEntry } from "@/types/agents";
import { useTranslations } from "next-intl";

/** The two fields this panel draws itself; the rest is the generated form. */
const HAND_ROLLED = ["provider", "model"];

interface ImageGenerationSectionProps {
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
 * Whose model draws, and which one - two selects, because it is two decisions.
 *
 * It was one field of whatever the schema enumerated: two entries, hand-written,
 * while OpenAI and Google each ship several image models and ship more every
 * quarter. Both lists come from the server, and both for a reason: whether a
 * provider can draw at all is `supported_native_tools()` on the SDK's model class,
 * and which models it offers is `app/core/catalog/image_models.json` - so a model
 * released this morning is one catalog entry, and an SDK that teaches a fourth
 * provider needs nothing here.
 *
 * Each model carries a sentence saying when to reach for it, which is the reason
 * the catalog is a file rather than an enum: a dropdown of four ids is a decision
 * made by guessing.
 */
export function ImageGenerationSection({
  definition,
  binding,
  onChange,
  onToggleEnabled,
  readOnly,
  disabled,
  configProblems,
}: ImageGenerationSectionProps) {
  const t = useTranslations("agents");
  const { providers, isLoading, isError } = useImageProviders();
  const configErrors = capabilityConfigErrors(configProblems ?? [], binding.id);
  const copyFor = useCapabilityFieldCopy(binding.id);

  if (!definition) return null;

  const resolved = resolveOffering(providers, binding.config);

  const setConfig = (patch: Record<string, unknown>) =>
    onChange({ ...binding, config: { ...binding.config, ...patch } });

  const controls = (
    <div className="space-y-4">
      <ProviderModelFields
        idPrefix="image"
        providers={providers}
        resolved={resolved}
        disabled={disabled}
        onChange={setConfig}
        copy={{
          provider: t("imageProvider"),
          providerPlaceholder: t("imageProviderPlaceholder"),
          providerDetail: t("imageProviderDetail"),
          model: t("imageModel"),
          modelPlaceholder: t("imageModelPlaceholder"),
          modelDetail: t("imageModelDetail"),
          unknownProvider: (provider) => t("imageModelUnknownProvider", { provider }),
        }}
      />

      {isError && <p className="text-destructive text-xs">{t("imageProvidersUnavailable")}</p>}
      {isLoading && <p className="text-muted-foreground text-xs">{t("imageProvidersLoading")}</p>}

      {/* Everything else the capability offers, generated as always - the quality,
          the size, the aspect ratio. Subtracted rather than listed, so a field
          added to the config appears on its own. The delegation panel's shape. */}
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
      // The provider shown before one is picked is the catalog's first, and the
      // key is gated on it (#2258): without it the picker stayed hidden.
      resolvedConfig={
        resolved.current === undefined ? undefined : { provider: resolved.current.provider }
      }
      // The controls above *are* this capability's configuration, the generated
      // fields included: drawing the form again would double every field.
      hideConfigForm
    />
  );
}
