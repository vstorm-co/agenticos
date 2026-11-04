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
import { SpeechVoiceChoices, storedVoices } from "@/components/agents/speech-voice-choices";
import {
  Input,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { useTextToSpeechProviders } from "@/hooks/use-model-providers";
import { capabilityConfigErrors } from "@/lib/agent-spec";
import type { FieldProblem } from "@/lib/api-error";
import type { CapabilityBindingSpec, CapabilityCatalogEntry } from "@/types/agents";
import { useTranslations } from "next-intl";

/** The fields this panel draws itself; the rest is the generated form. */
const HAND_ROLLED = ["provider", "model", "voice", "voices", "output_format"];

interface TextToSpeechSectionProps {
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
 * Whose voice, which model, and which of its voices - the image panel's two
 * selects plus a third, so choosing a voice feels like choosing a painter.
 *
 * The voices come from the catalog, per model, because OpenAI's older models
 * speak in only some of its voices. ElevenLabs lists none: its voices belong to
 * the account, so the third control is a field for the voice id instead.
 */
export function TextToSpeechSection({
  definition,
  binding,
  onChange,
  onToggleEnabled,
  readOnly,
  disabled,
  configProblems,
}: TextToSpeechSectionProps) {
  const t = useTranslations("agents");
  const { providers, isLoading, isError } = useTextToSpeechProviders();
  const configErrors = capabilityConfigErrors(configProblems ?? [], binding.id);
  const copyFor = useCapabilityFieldCopy(binding.id);

  if (!definition) return null;

  const resolved = resolveOffering(providers, binding.config);
  const voices = resolved.selected?.voices ?? [];
  const storedVoice = typeof binding.config.voice === "string" ? binding.config.voice : "";
  // Shown as the model's first voice when none is stored, which is what the
  // server resolves to - the same reason the provider and model are resolved.
  const voice = voices.some((entry) => entry.id === storedVoice)
    ? storedVoice
    : (voices[0]?.id ?? "");

  const setConfig = (patch: Record<string, unknown>) =>
    onChange({ ...binding, config: { ...binding.config, ...patch } });

  /** The config with these other voices, or with no list at all when there are none. */
  const withVoices = (config: Record<string, unknown>, others: { id: string }[]) => {
    const rest = withoutConfig(config, ["voices"]);
    return others.length > 0 ? { ...rest, voices: others } : rest;
  };

  /**
   * A new usual voice leaves the other voices: the list hides the usual one, so
   * left in it would be a choice nobody can see or untick.
   */
  const chooseVoice = (next: string) =>
    onChange({
      ...binding,
      config: withVoices(
        { ...binding.config, voice: next },
        storedVoices(binding.config.voices).filter((entry) => entry.id !== next),
      ),
    });

  /**
   * A voice or a format chosen for one provider means nothing on another, and a
   * voice one model speaks in may be one the next does not - OpenAI's `tts-1` has
   * nine of its thirteen. Kept only where the new choice still offers it - or,
   * on a provider whose voices belong to the account, on any of its models,
   * since the catalog lists none and the id is the author's own. The other
   * voices the agent may choose follow the same rule, one by one.
   */
  const chooseOffering = (patch: { provider?: string; model: string }) => {
    const next = resolveOffering(providers, { ...binding.config, ...patch });
    const offered = next.selected?.voices.map((entry) => entry.id) ?? [];
    const sameProvider = patch.provider === undefined;
    const accountVoices = next.current?.account_voices === true;
    const keepVoice = sameProvider && (accountVoices || offered.includes(storedVoice));
    // The voice the new model will speak in leaves the others, where it would be
    // hidden - the same reason choosing it by hand takes it out.
    const nextUsual = keepVoice && storedVoice !== "" ? storedVoice : offered[0];
    const others = sameProvider
      ? storedVoices(binding.config.voices).filter(
          (entry) => (accountVoices || offered.includes(entry.id)) && entry.id !== nextUsual,
        )
      : [];
    const kept = Object.fromEntries(
      Object.entries(binding.config).filter(
        ([name]) =>
          (name !== "voice" || keepVoice) &&
          name !== "voices" &&
          (name !== "output_format" || sameProvider),
      ),
    );
    // A key is the provider's: kept across a switch it would be sent to the next
    // one, since publish checks only that it is an API key.
    const secret_id = patch.provider === undefined ? binding.secret_id : null;
    onChange({ ...binding, secret_id, config: withVoices({ ...kept, ...patch }, others) });
  };

  const controls = (
    <div className="space-y-4">
      <ProviderModelFields
        idPrefix="speech"
        providers={providers}
        resolved={resolved}
        disabled={disabled}
        onChange={chooseOffering}
        copy={{
          provider: t("speechProvider"),
          providerPlaceholder: t("speechProviderPlaceholder"),
          providerDetail: t("speechProviderDetail"),
          model: t("speechModel"),
          modelPlaceholder: t("speechModelPlaceholder"),
          modelDetail: t("speechModelDetail"),
          unknownProvider: (provider) => t("speechModelUnknownProvider", { provider }),
        }}
      />

      {resolved.current !== undefined && (
        <div className="space-y-1.5">
          <Label htmlFor="speech-voice">{t("speechVoice")}</Label>
          {resolved.current.account_voices ? (
            <Input
              id="speech-voice"
              value={storedVoice}
              disabled={disabled}
              placeholder={t("speechVoiceIdPlaceholder")}
              onChange={(event) => setConfig({ voice: event.target.value })}
            />
          ) : (
            <Select
              value={voice}
              disabled={disabled || voices.length === 0}
              onValueChange={chooseVoice}
            >
              <SelectTrigger id="speech-voice">
                <SelectValue placeholder={t("speechVoicePlaceholder")} />
              </SelectTrigger>
              <SelectContent>
                {voices.map((entry) => (
                  <SelectItem key={entry.id} value={entry.id}>
                    {entry.description ? `${entry.name} - ${entry.description}` : entry.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
          <p className="text-muted-foreground text-xs">
            {resolved.current.account_voices
              ? t("speechAccountVoiceDetail", { provider: resolved.current.name })
              : t("speechVoiceDetail")}
          </p>
        </div>
      )}

      {resolved.current !== undefined && (
        <SpeechVoiceChoices
          provider={resolved.current}
          offered={voices}
          usualVoice={resolved.current.account_voices ? storedVoice : voice}
          value={storedVoices(binding.config.voices)}
          errors={configErrors}
          disabled={disabled}
          onChange={(others) =>
            onChange({ ...binding, config: withVoices(binding.config, others) })
          }
        />
      )}

      {resolved.current !== undefined && (
        <div className="space-y-1.5">
          <Label htmlFor="speech-format">{t("speechFormat")}</Label>
          <Select
            value={
              typeof binding.config.output_format === "string" &&
              resolved.current.formats.includes(binding.config.output_format)
                ? binding.config.output_format
                : resolved.current.formats[0]
            }
            disabled={disabled || resolved.current.formats.length < 2}
            onValueChange={(next) => setConfig({ output_format: next })}
          >
            <SelectTrigger id="speech-format">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {resolved.current.formats.map((entry) => (
                <SelectItem key={entry} value={entry}>
                  {entry}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <p className="text-muted-foreground text-xs">{t("speechFormatDetail")}</p>
        </div>
      )}

      {/* `voices` says its own, beside the rows it is about. */}
      <DrawnFieldErrors
        errors={configErrors}
        fields={HAND_ROLLED.filter((field) => field !== "voices")}
      />

      {isError && <p className="text-destructive text-xs">{t("speechProvidersUnavailable")}</p>}
      {isLoading && <p className="text-muted-foreground text-xs">{t("speechProvidersLoading")}</p>}

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
      resolvedConfig={
        resolved.current === undefined ? undefined : { provider: resolved.current.provider }
      }
      // The controls above *are* this capability's configuration, the generated
      // fields included: drawing the form again would double every field.
      hideConfigForm
    />
  );
}
