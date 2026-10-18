"use client";

import { TriangleAlert } from "lucide-react";
import { useTranslations } from "next-intl";

import { ChoiceGroup } from "@/components/settings/choice-group";
import { SpeechKeyField, useSpeechKeyCheck } from "@/components/vault/speech-key-field";
import {
  FormField,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { ProviderIcon } from "@/components/vault/provider-icon";
import { useSpeechToTextProviders } from "@/hooks/use-model-providers";
import type { ChannelPlatform, InheritedSpeechToText } from "@/types/channels";

export type TranscriptionMode = "inherit" | "choose" | "off";

/** The value the picker edits: a mode, and under `choose` a pair and its key. */
export interface TranscriptionChoice {
  mode: TranscriptionMode;
  provider: string | null;
  model: string | null;
  /** The vault key the bot's own pair is sent with; null while none is chosen. */
  secretId: string | null;
}

export const INHERIT: TranscriptionChoice = {
  mode: "inherit",
  provider: null,
  model: null,
  secretId: null,
};

/** How a stored bot reads into the picker: off, its own pair, or inheriting. */
export function choiceOf(bot: {
  transcribe_voice_notes: boolean;
  speech_to_text_provider: string | null;
  speech_to_text_model: string | null;
  speech_to_text_secret_id: string | null;
}): TranscriptionChoice {
  if (!bot.transcribe_voice_notes) return { ...INHERIT, mode: "off" };
  if (bot.speech_to_text_provider && bot.speech_to_text_model) {
    return {
      mode: "choose",
      provider: bot.speech_to_text_provider,
      model: bot.speech_to_text_model,
      secretId: bot.speech_to_text_secret_id,
    };
  }
  return INHERIT;
}

interface TranscriptionFieldsProps {
  value: TranscriptionChoice;
  onChange: (next: TranscriptionChoice) => void;
  /** Prefix for the input ids, so two of these on one page do not collide. */
  idPrefix: string;
  platform: ChannelPlatform;
  /**
   * What inheriting resolves to, for the hint beside it. `undefined` while it
   * is being read, which says nothing rather than something wrong.
   */
  inherited: InheritedSpeechToText | null | undefined;
  /** The server's refusal of the key, if it named one. */
  keyError?: string;
}

/**
 * Whether this bot transcribes voice messages, and on what (#1797).
 *
 * Three answers. **Inherit** (the default) uses the agent the bot serves, then
 * the organization - and with neither naming a provider, nothing is
 * transcribed, so inheriting costs nothing until somebody sets one up.
 * **Choose** names the bot's own pair. **Off** never transcribes, whatever the
 * agent or the organization say.
 *
 * Shared by the add and edit dialogs, unlike the credential fields beside them:
 * those mean different things in the two places - set a value against replace one
 * that is never read back - and this means exactly one thing in both.
 *
 * **Both halves move together, with their key.** A provider with no model has
 * nothing to call and a model with no provider has nowhere to send it, so
 * choosing a provider takes its first model, and leaving Choose clears both and
 * the key. The key is an organization-wide one for the provider - a bot's voice
 * notes are paid for on everybody's behalf - and a provider change drops the
 * old one, since a key never goes to another provider. Choose starts on the
 * first provider with such a key; one without is marked, and the key field
 * offers to add one.
 *
 * Absent when the deployment offers nothing - every provider it knows wants a
 * service account, say - because an empty picker is a control that reads as a
 * choice somebody failed to make.
 */
export function TranscriptionFields({
  value,
  onChange,
  idPrefix,
  platform,
  inherited,
  keyError,
}: TranscriptionFieldsProps) {
  const t = useTranslations("pages.channels");
  const { providers } = useSpeechToTextProviders();
  const hasKey = useSpeechKeyCheck(true);

  if (providers.length === 0) return null;

  const chosen = providers.find((entry) => entry.provider === value.provider);
  const nameOf = (id: string) => providers.find((entry) => entry.provider === id)?.name ?? id;

  const setMode = (mode: TranscriptionMode) => {
    if (mode !== "choose") {
      onChange({ ...INHERIT, mode });
      return;
    }
    // The first provider with a key a bot may use, or the first offered when
    // none has - the key field then offers to add one.
    const first = providers.find((entry) => hasKey(entry.provider)) ?? providers[0]!;
    onChange({ mode, provider: first.provider, model: first.models[0]!.id, secretId: null });
  };

  // Telegram sends a voice note as Ogg/Opus and Slack's desktop app records a
  // clip as WebM, and Mistral lists neither: an inherited Mistral is the case
  // nobody chose and nobody would think to check. Mattermost carries whatever
  // was uploaded, so there is no one format to warn about.
  const goesTo = value.mode === "choose" ? value.provider : (inherited?.provider ?? null);
  const unreadByMistral = platform !== "mattermost" && value.mode !== "off" && goesTo === "mistral";

  return (
    <div className="space-y-3">
      <div className="space-y-2">
        <p id={`${idPrefix}-stt-mode`} className="text-sm font-medium">
          {t("transcriptionProvider")}
        </p>
        <ChoiceGroup
          labelledBy={`${idPrefix}-stt-mode`}
          value={value.mode}
          options={[
            { value: "inherit", label: t("transcriptionInherit") },
            { value: "choose", label: t("transcriptionChoose") },
            { value: "off", label: t("transcriptionOff") },
          ]}
          onChange={setMode}
        />
        <p className="text-muted-foreground text-xs">
          {value.mode === "off"
            ? t("transcriptionOffHint")
            : value.mode === "choose"
              ? t("transcriptionProviderHint")
              : inheritHint(t, inherited, nameOf)}
        </p>
        {value.mode === "inherit" && inherited && !inherited.has_key && (
          <p className="text-warning flex gap-2 text-xs" role="note">
            <TriangleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
            {t("transcriptionInheritedNoKey")}
          </p>
        )}
      </div>

      {value.mode === "choose" && (
        <div className="grid gap-4 sm:grid-cols-2">
          <FormField label={t("transcriptionEngine")} htmlFor={`${idPrefix}-stt-provider`}>
            <Select
              value={value.provider ?? undefined}
              onValueChange={(next) => {
                // `next` is one of the options below, and each catalog entry has a model.
                const entry = providers.find((candidate) => candidate.provider === next)!;
                onChange({
                  mode: "choose",
                  provider: next,
                  model: entry.models[0]!.id,
                  secretId: null,
                });
              }}
            >
              <SelectTrigger id={`${idPrefix}-stt-provider`}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {providers.map((entry) => {
                  const label = hasKey(entry.provider)
                    ? entry.name
                    : t("transcriptionProviderNoKey", { name: entry.name });
                  return (
                    <SelectItem key={entry.provider} value={entry.provider} textValue={label}>
                      <span className="flex items-center gap-2">
                        <ProviderIcon provider={entry.provider} className="h-3.5 w-3.5" />
                        {label}
                      </span>
                    </SelectItem>
                  );
                })}
              </SelectContent>
            </Select>
          </FormField>

          <FormField
            label={t("transcriptionModel")}
            htmlFor={`${idPrefix}-stt-model`}
            description={
              chosen?.models.find((model) => model.id === value.model)?.description ??
              t("transcriptionModelHint")
            }
          >
            <Select
              value={value.model ?? ""}
              onValueChange={(next) => onChange({ ...value, mode: "choose", model: next })}
            >
              <SelectTrigger id={`${idPrefix}-stt-model`}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {(chosen?.models ?? []).map((model) => (
                  <SelectItem key={model.id} value={model.id} textValue={model.name}>
                    {model.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FormField>
          {chosen && (
            <SpeechKeyField
              id={`${idPrefix}-stt-key`}
              provider={chosen.provider}
              providerName={chosen.name}
              value={value.secretId}
              orgVisibleOnly
              error={keyError}
              onChange={(secretId) => onChange({ ...value, mode: "choose", secretId })}
            />
          )}
        </div>
      )}

      {unreadByMistral && (
        <p className="text-warning flex gap-2 text-xs" role="note">
          <TriangleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
          {t("transcriptionMistralFormat", { platform })}
        </p>
      )}
    </div>
  );
}

/** What "inherit" resolves to, in words: whose pair, or that there is none. */
function inheritHint(
  t: ReturnType<typeof useTranslations<"pages.channels">>,
  inherited: InheritedSpeechToText | null | undefined,
  nameOf: (id: string) => string,
): string {
  if (inherited === undefined) return t("transcriptionInheritHint");
  if (inherited === null) return t("transcriptionInheritsNothing");
  const pair = t("transcriptionPair", {
    provider: nameOf(inherited.provider),
    model: inherited.model,
  });
  return inherited.pair_source === "agent" && inherited.agent_name
    ? t("transcriptionInheritsFromAgent", { pair, agent: inherited.agent_name })
    : t("transcriptionInheritsFromOrg", { pair });
}
