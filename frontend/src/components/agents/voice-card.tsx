"use client";

import { useMemo } from "react";
import { Info } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import { ChoiceGroup } from "@/components/settings/choice-group";
import { SpeechKeyField, useSpeechKeyCheck } from "@/components/vault/speech-key-field";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  FormField,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { useOrganizationList } from "@/hooks";
import { useSpeechToTextProviders, type SpeechToTextProvider } from "@/hooks/use-model-providers";
import { useOrgStore } from "@/stores";
import type { SpeechToTextSpec } from "@/types/agents";

/** Radix `SelectItem` refuses `""`, so inheriting the language needs a value of its own. */
const INHERIT = "inherit";

type PairMode = "inherit" | "choose";

interface VoiceCardProps {
  value: SpeechToTextSpec | null | undefined;
  onChange: (next: SpeechToTextSpec | null) => void;
  disabled?: boolean;
}

/**
 * Which engine and language this agent's speech is transcribed with.
 *
 * An override on the organization's Voice settings, read for dictation in the
 * chat composer and for voice notes sent to this agent's channel bots. Part of
 * the spec like every other card on the Build tab: it autosaves into the draft
 * and takes effect when the agent is published.
 *
 * **The provider, model and key move as one**, and the language on its own - so
 * a Polish agent can keep the organization's provider and its key. The key is
 * any API key for the provider this person can see: publishing lends it to
 * whoever runs the agent. The block is always written with all four keys in the
 * spec's order and explicit nulls, and an all-null block is written as `null`,
 * because the server stores it that way and the Builder compares the draft as
 * JSON: any other spelling would show as an unpublished change that is not one.
 */
export function VoiceCard({ value, onChange, disabled }: VoiceCardProps) {
  const t = useTranslations("agents");
  const activeOrgId = useOrgStore((state) => state.activeOrgId);
  const { data: orgs } = useOrganizationList();
  const org = orgs?.find((candidate) => candidate.id === activeOrgId) ?? null;
  const { providers, languages } = useSpeechToTextProviders();
  const languageName = useLanguageName();

  const provider = value?.provider ?? null;
  const model = value?.model ?? null;
  const language = value?.language ?? null;
  const secretId = value?.secret_id ?? null;
  const mode: PairMode = provider !== null || model !== null ? "choose" : "inherit";
  const hasKey = useSpeechKeyCheck(false);

  const write = (next: Partial<SpeechToTextSpec>) => {
    const block = {
      provider: next.provider !== undefined ? next.provider : provider,
      model: next.model !== undefined ? next.model : model,
      language: next.language !== undefined ? next.language : language,
      secret_id: next.secret_id !== undefined ? next.secret_id : secretId,
    };
    const empty =
      block.provider === null &&
      block.model === null &&
      block.language === null &&
      block.secret_id === null;
    onChange(empty ? null : block);
  };

  const choose = (next: PairMode) => {
    if (next === "inherit") {
      write({ provider: null, model: null, secret_id: null });
      return;
    }
    // A pair at once, never half of one: the first provider with a key this
    // person can choose, or the first offered when none has - the key field
    // then offers to add one. The group is disabled while the catalog is
    // empty, so there is a first. The key is chosen below, never carried.
    const first = providers.find((entry) => hasKey(entry.provider)) ?? providers[0]!;
    write({ provider: first.provider, model: first.models[0]!.id, secret_id: null });
  };

  // By id while the catalog is unread.
  const nameOf = (id: string) => providers.find((entry) => entry.provider === id)?.name ?? id;
  const orgPair =
    org?.speech_to_text_provider && org.speech_to_text_model
      ? t("voiceOrgPair", {
          provider: nameOf(org.speech_to_text_provider),
          model: org.speech_to_text_model,
        })
      : null;
  const engine = org?.chat_dictation ?? null;

  return (
    // The anchor the composer's crossed-out microphone links to.
    <Card id="agent-voice" className="scroll-mt-20">
      <CardHeader>
        <CardTitle>{t("voiceTitle")}</CardTitle>
        <CardDescription>{t("voiceDescription")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-4">
        <Notes engine={engine} orgHasPair={orgPair !== null} choosing={mode === "choose"} />
        <div className="space-y-2">
          <p id="agent-voice-pair" className="text-sm font-medium">
            {t("voicePair")}
          </p>
          <ChoiceGroup
            labelledBy="agent-voice-pair"
            value={mode}
            disabled={disabled || providers.length === 0}
            options={[
              { value: "inherit", label: t("voicePairInherit") },
              { value: "choose", label: t("voicePairChoose") },
            ]}
            onChange={choose}
          />
          {mode === "inherit" && (
            <p className="text-muted-foreground text-xs">
              {orgPair ? t("voiceInherits", { pair: orgPair }) : t("voiceOrgNoPair")}
            </p>
          )}
        </div>
        {mode === "choose" && (
          <PairFields
            providers={providers}
            provider={provider}
            model={model}
            secretId={secretId}
            hasKey={hasKey}
            disabled={disabled}
            onChange={write}
          />
        )}
        <FormField
          label={t("voiceLanguage")}
          htmlFor="agent-voice-language"
          description={t("voiceLanguageHint")}
        >
          <Select
            value={language ?? INHERIT}
            disabled={disabled}
            onValueChange={(next) => write({ language: next === INHERIT ? null : next })}
          >
            <SelectTrigger id="agent-voice-language">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={INHERIT}>
                {t("voiceLanguageInherit", {
                  language: org?.speech_to_text_language
                    ? languageName(org.speech_to_text_language)
                    : t("voiceLanguageAuto"),
                })}
              </SelectItem>
              {languages
                .map((code) => ({ code, name: languageName(code) }))
                .sort((a, b) => a.name.localeCompare(b.name))
                .map(({ code, name }) => (
                  <SelectItem key={code} value={code}>
                    {t("voiceLanguageOption", { name, code })}
                  </SelectItem>
                ))}
            </SelectContent>
          </Select>
        </FormField>
      </CardContent>
    </Card>
  );
}

/** A language's name in the reader's own language, or its code where unnamed. */
function useLanguageName(): (code: string) => string {
  const locale = useLocale();
  return useMemo(() => {
    // `fallback: "code"` answers a code it cannot name with the code itself.
    const names = new Intl.DisplayNames([locale], { type: "language", fallback: "code" });
    return (code: string) => names.of(code)!;
  }, [locale]);
}

interface NotesProps {
  engine: string | null;
  orgHasPair: boolean;
  choosing: boolean;
}

/**
 * What this override changes, where that is not the obvious answer: nothing in
 * the chat when the organization dictates in the browser or not at all, and the
 * whole of dictation when the organization has no provider of its own.
 */
function Notes({ engine, orgHasPair, choosing }: NotesProps) {
  const t = useTranslations("agents");
  let note: string | null = null;
  if (engine === "off" || engine === "browser") {
    note = t("voiceNoteChannelsOnly", { engine });
  } else if (engine === "server" && !orgHasPair) {
    note = choosing ? t("voiceNoteOwnProvider") : t("voiceNoteNoProvider");
  }
  if (note === null) return null;
  return (
    <p className="bg-muted text-muted-foreground flex gap-2 rounded-lg px-3 py-2 text-xs">
      <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
      {note}
    </p>
  );
}

interface PairFieldsProps {
  providers: SpeechToTextProvider[];
  provider: string | null;
  model: string | null;
  secretId: string | null;
  hasKey: (provider: string) => boolean;
  disabled?: boolean;
  onChange: (next: Partial<SpeechToTextSpec>) => void;
}

/** The provider and its model, from the speech-to-text catalog, and the key they go with. */
function PairFields({
  providers,
  provider,
  model,
  secretId,
  hasKey,
  disabled,
  onChange,
}: PairFieldsProps) {
  const t = useTranslations("agents");
  const chosen = providers.find((entry) => entry.provider === provider);
  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <FormField
        label={t("voiceProvider")}
        htmlFor="agent-voice-provider"
        description={t("voiceProviderHint")}
      >
        <Select
          value={provider ?? undefined}
          disabled={disabled}
          onValueChange={(next) => {
            // `next` is one of the options below, and each catalog entry has a
            // model. The key was the old provider's, so it goes with it.
            const entry = providers.find((candidate) => candidate.provider === next)!;
            onChange({ provider: next, model: entry.models[0]!.id, secret_id: null });
          }}
        >
          <SelectTrigger id="agent-voice-provider">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {providers.map((entry) => {
              const label = hasKey(entry.provider)
                ? entry.name
                : t("voiceProviderNoKey", { name: entry.name });
              return (
                <SelectItem key={entry.provider} value={entry.provider} textValue={label}>
                  {label}
                </SelectItem>
              );
            })}
          </SelectContent>
        </Select>
      </FormField>
      <FormField label={t("voiceModel")} htmlFor="agent-voice-model">
        <Select
          value={model ?? undefined}
          disabled={disabled}
          onValueChange={(next) => onChange({ model: next })}
        >
          <SelectTrigger id="agent-voice-model">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {(chosen?.models ?? []).map((entry) => (
              <SelectItem key={entry.id} value={entry.id} textValue={entry.name}>
                {entry.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </FormField>
      {chosen && (
        <SpeechKeyField
          id="agent-voice-key"
          provider={chosen.provider}
          providerName={chosen.name}
          value={secretId}
          orgVisibleOnly={false}
          disabled={disabled}
          onChange={(next) => onChange({ secret_id: next })}
        />
      )}
    </div>
  );
}
