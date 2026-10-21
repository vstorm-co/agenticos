"use client";

import { Info } from "lucide-react";
import { useState } from "react";
import { useTranslations } from "next-intl";

import {
  VoiceConversationFields,
  type VoiceConversationProps,
} from "@/components/agents/voice-conversation-fields";
import { ChoiceGroup } from "@/components/settings/choice-group";
import { ProviderIcon } from "@/components/vault/provider-icon";
import { SpeechKeyField, useSpeechKeyCheck } from "@/components/vault/speech-key-field";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  FormField,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Switch,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui";
import { useOrganizationList } from "@/hooks";
import { useLanguageName } from "@/hooks/use-language-name";
import { useSpeechToTextProviders, type SpeechToTextProvider } from "@/hooks/use-model-providers";
import { useOrgStore } from "@/stores";
import type { SpeechToTextSpec } from "@/types/agents";

/** Radix `SelectItem` refuses `""`, so inheriting the language needs a value of its own. */
const INHERIT = "inherit";

type PairMode = "inherit" | "choose";

/**
 * What a link to this agent's dictation setup ends in - the composer's crossed-out
 * microphone. The card scrolls into view on it and opens on its Dictation tab.
 */
export const AGENT_DICTATION_ANCHOR = "agent-voice-dictation";

type VoiceTab = "calls" | "dictation";

interface VoiceCardProps {
  value: SpeechToTextSpec | null | undefined;
  onChange: (next: SpeechToTextSpec | null) => void;
  disabled?: boolean;
  /** The agent's voice conversations (#54), on a tab beside dictation. */
  conversation?: Omit<VoiceConversationProps, "disabled">;
}

/**
 * How this agent is dictated to, and which provider and language transcribe it.
 *
 * Its Dictation switch decides whether the chat composer sends recordings to a
 * provider; without it, or with no provider and key to send to, the browser's
 * own recognition transcribes. The provider and language are an override on
 * the organization's, read for that and for voice notes sent to this agent's
 * channel bots, whatever the switch. Part of
 * the spec like every other card on the Build tab: it autosaves into the draft
 * and takes effect when the agent is published.
 *
 * **The provider, model and key move as one**, and the language on its own - so
 * a Polish agent can keep the organization's provider and its key. The key is
 * any API key for the provider this person can see: publishing lends it to
 * whoever runs the agent. The block is always written with every key in the
 * spec's order and explicit nulls, and a block at its defaults is written as `null`,
 * because the server stores it that way and the Builder compares the draft as
 * JSON: any other spelling would show as an unpublished change that is not one.
 */
export function VoiceCard({ value, onChange, disabled, conversation }: VoiceCardProps) {
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
  const dictation = value?.dictation ?? false;
  const mode: PairMode = provider !== null || model !== null ? "choose" : "inherit";
  const hasKey = useSpeechKeyCheck(false);

  const write = (next: Partial<SpeechToTextSpec>) => {
    const block = {
      provider: next.provider !== undefined ? next.provider : provider,
      model: next.model !== undefined ? next.model : model,
      language: next.language !== undefined ? next.language : language,
      secret_id: next.secret_id !== undefined ? next.secret_id : secretId,
      dictation: next.dictation !== undefined ? next.dictation : dictation,
    };
    const empty =
      block.provider === null &&
      block.model === null &&
      block.language === null &&
      block.secret_id === null &&
      !block.dictation;
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
  // The card renders once the agent has loaded, in the browser, so the hash a
  // link arrived with is there to read.
  const [tab, setTab] = useState<VoiceTab>(() =>
    !conversation || window.location.hash === `#${AGENT_DICTATION_ANCHOR}` ? "dictation" : "calls",
  );

  return (
    // The anchor the composer's crossed-out microphone links to.
    <Card id="agent-voice" data-tour="agent-voice" className="scroll-mt-20">
      <span id={AGENT_DICTATION_ANCHOR} className="block scroll-mt-20" aria-hidden />
      <CardHeader>
        <CardTitle>{t("voiceTitle")}</CardTitle>
        <CardDescription>{t("voiceDescription")}</CardDescription>
      </CardHeader>
      {/* Two things people do with their voice, told apart rather than stacked:
          a call is a live, two-way conversation on a realtime model; dictation
          turns speech into text on a transcription model. Each is set up on its
          own tab, under one sentence saying what it is. */}
      <CardContent>
        <Tabs value={tab} onValueChange={(next) => setTab(next as VoiceTab)}>
          <TabsList>
            {conversation && <TabsTrigger value="calls">{t("voiceTabCalls")}</TabsTrigger>}
            <TabsTrigger value="dictation">{t("voiceTabDictation")}</TabsTrigger>
          </TabsList>
          {conversation && (
            <TabsContent value="calls" className="mt-4 space-y-4">
              <p className="text-muted-foreground text-sm">{t("voiceCallsLead")}</p>
              <VoiceConversationFields {...conversation} disabled={disabled} />
            </TabsContent>
          )}
          <TabsContent value="dictation" className="mt-4 space-y-4">
            <p className="text-muted-foreground text-sm">{t("voiceDictationLead")}</p>
            <div className="flex items-start justify-between gap-4">
              <div className="space-y-0.5">
                <Label htmlFor="agent-voice-dictation-switch">{t("voiceDictationProvider")}</Label>
                <p className="text-muted-foreground text-xs">{t("voiceDictationProviderHint")}</p>
              </div>
              <Switch
                id="agent-voice-dictation-switch"
                checked={dictation}
                disabled={disabled}
                onCheckedChange={(on) => write({ dictation: on })}
              />
            </div>
            <Notes dictation={dictation} hasPair={orgPair !== null || mode === "choose"} />
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
          </TabsContent>
        </Tabs>
      </CardContent>
    </Card>
  );
}

interface NotesProps {
  dictation: boolean;
  /** A pair resolves: the agent's own, or the organization's it inherits. */
  hasPair: boolean;
}

/**
 * What the switch and the provider below do together, where that is not the
 * obvious answer: with the switch off they only change channel voice notes, and
 * with it on but nothing to send to, the browser still transcribes.
 */
function Notes({ dictation, hasPair }: NotesProps) {
  const t = useTranslations("agents");
  let note: string | null = null;
  if (!dictation) {
    note = t("voiceNoteChannelsOnly");
  } else if (!hasPair) {
    note = t("voiceNoteNoProvider");
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
        label={t("voiceModel")}
        htmlFor="agent-voice-model"
        // What the catalog says about the one chosen: which to reach for is the
        // question the picker is asked.
        description={chosen?.models.find((entry) => entry.id === model)?.description}
      >
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
