"use client";

import { CapabilityDetail } from "@/components/agents/capability-settings";
import { SchemaForm } from "@/components/agents/schema-form";
import {
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { ProviderIcon } from "@/components/vault/provider-icon";
import { useImageProviders } from "@/hooks/use-model-providers";
import { capabilityConfigErrors } from "@/lib/agent-spec";
import type { FieldProblem } from "@/lib/api-error";
import type { CapabilityBindingSpec, CapabilityCatalogEntry, JsonSchema } from "@/types/agents";
import { useTranslations } from "next-intl";

/** The two fields this panel draws itself; the rest is the generated form. */
const HAND_ROLLED = ["provider", "model"];

interface ImageGenerationSectionProps {
  definition: CapabilityCatalogEntry | undefined;
  binding: CapabilityBindingSpec;
  onChange: (binding: CapabilityBindingSpec) => void;
  onToggleEnabled?: () => void;
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
  disabled,
  configProblems,
}: ImageGenerationSectionProps) {
  const t = useTranslations("agents");
  const { providers, isLoading, isError } = useImageProviders();
  const configErrors = capabilityConfigErrors(configProblems ?? [], binding.id);

  if (!definition) return null;

  const provider = typeof binding.config.provider === "string" ? binding.config.provider : "";
  const model = typeof binding.config.model === "string" ? binding.config.model : "";
  const current = providers.find((entry) => entry.provider === provider);

  const setConfig = (patch: Record<string, unknown>) =>
    onChange({ ...binding, config: { ...binding.config, ...patch } });

  /** Switching provider re-points the model, because an id is not portable. */
  const chooseProvider = (next: string) => {
    const entry = providers.find((candidate) => candidate.provider === next);
    // The select only ever hands back a value from the list above, so the lookup
    // cannot miss; the `?.` is the type checker's price for that rather than a
    // fallback anybody reaches.
    setConfig({ provider: next, model: entry?.models[0]?.id ?? "" });
  };

  const controls = (
    <div className="space-y-4">
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="space-y-1.5">
          <Label htmlFor="image-provider">{t("imageProvider")}</Label>
          <Select
            value={current?.provider ?? ""}
            disabled={disabled || providers.length === 0}
            onValueChange={chooseProvider}
          >
            <SelectTrigger id="image-provider">
              <SelectValue placeholder={t("imageProviderPlaceholder")} />
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
          <p className="text-muted-foreground text-xs">{t("imageProviderDetail")}</p>
        </div>

        <div className="space-y-1.5">
          <Label htmlFor="image-model">{t("imageModel")}</Label>
          <Select
            value={model}
            disabled={disabled || current === undefined}
            onValueChange={(next) => setConfig({ model: next })}
          >
            <SelectTrigger id="image-model">
              <SelectValue placeholder={t("imageModelPlaceholder")} />
            </SelectTrigger>
            <SelectContent>
              {(current?.models ?? []).map((entry) => (
                <SelectItem key={entry.id} value={entry.id}>
                  {/* The name and what it is for, because four ids in a dropdown
                      is a decision made by guessing. */}
                  <span className="flex flex-col gap-0.5">
                    <span>{entry.name}</span>
                    <span className="text-muted-foreground text-xs">{entry.description}</span>
                  </span>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <p className="text-muted-foreground text-xs">
            {current === undefined && provider !== ""
              ? t("imageModelUnknownProvider", { provider })
              : t("imageModelDetail")}
          </p>
        </div>
      </div>

      {isError && <p className="text-destructive text-xs">{t("imageProvidersUnavailable")}</p>}
      {isLoading && <p className="text-muted-foreground text-xs">{t("imageProvidersLoading")}</p>}

      {/* Everything else the capability offers, generated as always - the quality,
          the size, the aspect ratio. Subtracted rather than listed, so a field
          added to the config appears on its own. The delegation panel's shape. */}
      {definition.config_schema && (
        <SchemaForm
          idPrefix={binding.id}
          schema={withoutHandRolled(definition.config_schema)}
          value={binding.config}
          disabled={disabled}
          errors={configErrors}
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
      disabled={disabled}
      configProblems={configProblems}
      settingsExtra={controls}
      // The controls above *are* this capability's configuration, the generated
      // fields included: drawing the form again would double every field.
      hideConfigForm
    />
  );
}

/**
 * The schema with the fields this panel draws itself taken out.
 *
 * Subtracting rather than listing what to keep, the same way the delegation panel
 * does it: a field added to `ImageGenerationConfig` should appear here on its own.
 */
function withoutHandRolled(schema: JsonSchema): JsonSchema {
  const properties = Object.fromEntries(
    Object.entries(schema.properties ?? {}).filter(([name]) => !HAND_ROLLED.includes(name)),
  );
  return { ...schema, properties };
}
