"use client";

import { TriangleAlert } from "lucide-react";
import { useTranslations } from "next-intl";

import { ChoiceGroup } from "@/components/settings/choice-group";
import {
  FormField,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { useSpeechToTextProviders } from "@/hooks/use-model-providers";
import type { ChannelPlatform, InheritedSpeechToText } from "@/types/channels";

export type TranscriptionMode = "inherit" | "choose" | "off";

/** The value the picker edits: a mode, and under `choose` both halves of a pair. */
export interface TranscriptionChoice {
  mode: TranscriptionMode;
  provider: string | null;
  model: string | null;
}

export const INHERIT: TranscriptionChoice = { mode: "inherit", provider: null, model: null };

/** How a stored bot reads into the picker: off, its own pair, or inheriting. */
export function choiceOf(bot: {
  transcribe_voice_notes: boolean;
  speech_to_text_provider: string | null;
  speech_to_text_model: string | null;
}): TranscriptionChoice {
  if (!bot.transcribe_voice_notes) return { mode: "off", provider: null, model: null };
  if (bot.speech_to_text_provider && bot.speech_to_text_model) {
    return {
      mode: "choose",
      provider: bot.speech_to_text_provider,
      model: bot.speech_to_text_model,
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
 * **Both halves move together.** A provider with no model has nothing to call and
 * a model with no provider has nowhere to send it, so choosing a provider takes
 * its first model, and leaving Choose clears both. The server enforces the same
 * rule against the stored row; this is what stops somebody meeting it.
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
}: TranscriptionFieldsProps) {
  const t = useTranslations("pages.channels");
  const { providers } = useSpeechToTextProviders();

  if (providers.length === 0) return null;

  const chosen = providers.find((entry) => entry.provider === value.provider);
  const nameOf = (id: string) => providers.find((entry) => entry.provider === id)?.name ?? id;

  const setMode = (mode: TranscriptionMode) => {
    if (mode !== "choose") {
      onChange({ mode, provider: null, model: null });
      return;
    }
    const first = providers[0]!;
    onChange({ mode, provider: first.provider, model: first.models[0]!.id });
  };

  // Telegram sends a voice note as Ogg/Opus, and Mistral lists neither: an
  // inherited Mistral is the case nobody chose and nobody would think to check.
  const goesTo = value.mode === "choose" ? value.provider : (inherited?.provider ?? null);
  const oggToMistral = platform === "telegram" && value.mode !== "off" && goesTo === "mistral";

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
      </div>

      {value.mode === "choose" && (
        <div className="grid gap-4 sm:grid-cols-2">
          <FormField label={t("transcriptionEngine")} htmlFor={`${idPrefix}-stt-provider`}>
            <Select
              value={value.provider ?? undefined}
              onValueChange={(next) => {
                // `next` is one of the options below, and each catalog entry has a model.
                const entry = providers.find((candidate) => candidate.provider === next)!;
                onChange({ mode: "choose", provider: next, model: entry.models[0]!.id });
              }}
            >
              <SelectTrigger id={`${idPrefix}-stt-provider`}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {providers.map((entry) => (
                  <SelectItem key={entry.provider} value={entry.provider} textValue={entry.name}>
                    {entry.name}
                  </SelectItem>
                ))}
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
              onValueChange={(next) =>
                onChange({ mode: "choose", provider: value.provider, model: next })
              }
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
        </div>
      )}

      {oggToMistral && (
        <p className="text-warning flex gap-2 text-xs" role="note">
          <TriangleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
          {t("transcriptionTelegramMistral")}
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
