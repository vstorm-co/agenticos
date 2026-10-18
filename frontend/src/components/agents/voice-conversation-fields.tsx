"use client";

import { Info } from "lucide-react";
import { useTranslations } from "next-intl";
import { useId, useState } from "react";

import { ProviderIcon } from "@/components/vault/provider-icon";
import { SpeechKeyField } from "@/components/vault/speech-key-field";
import {
  FormField,
  Input,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Switch,
  Textarea,
} from "@/components/ui";
import { useCapabilityCatalog } from "@/hooks/use-agents";
import { useChanged } from "@/hooks/use-changed";
import { useLanguageName } from "@/hooks/use-language-name";
import { useSpeechToTextProviders } from "@/hooks/use-model-providers";
import { useRealtimeModels } from "@/hooks/use-realtime-models";
import type { VoiceSpec } from "@/types/agents";
import type { RealtimeModel, RealtimeProvider } from "@/types/voice";

/** Radix `SelectItem` refuses `""`, so following the caller needs a value of its own. */
const FOLLOW_CALLER = "caller";
const MAX_MINUTES = 50;
const NOTE_LIMIT = 1000;

const EMPTY: VoiceSpec = {
  provider: null,
  model: null,
  deployment: null,
  base_model: null,
  secret_id: null,
  voice: null,
  language: null,
  max_call_seconds: null,
  voice_note: null,
};

export interface VoiceConversationProps {
  value: VoiceSpec | null | undefined;
  onChange: (next: VoiceSpec | null) => void;
  /** The capabilities this agent has on, to list the ones a call cannot use. */
  capabilityIds: string[];
  hasGuardrails: boolean;
  /** The organization's longest call, which an agent can only shorten. */
  orgMaxSeconds: number;
  disabled?: boolean;
}

/** The catalog model a block runs: Azure names it as the deployment's base. */
function modelOf(entry: RealtimeProvider | undefined, block: VoiceSpec): RealtimeModel | undefined {
  const id = entry?.deployment ? block.base_model : block.model;
  return entry?.models.find((model) => model.id === id);
}

/** A provider's first model, as the block that picks it: the key goes with the old provider. */
function firstOf(entry: RealtimeProvider): Partial<VoiceSpec> {
  const first = entry.models[0]!;
  return entry.deployment
    ? { provider: entry.provider, model: null, base_model: first.id, voice: first.default_voice }
    : {
        provider: entry.provider,
        model: first.id,
        base_model: null,
        deployment: null,
        voice: first.default_voice,
      };
}

/**
 * The agent's realtime model for voice conversations (#54): provider and model
 * (or an Azure deployment and its base model), the key, the voice, the
 * language, the longest call and a voice note - and what a call cannot do.
 *
 * Written like `VoiceCard`'s block: all nine keys in the spec's order with
 * explicit nulls, and switching calls off writes `null`, because the server
 * stores it that way and the Builder compares the draft as JSON.
 */
export function VoiceConversationFields(props: VoiceConversationProps) {
  const { value, onChange, disabled } = props;
  const t = useTranslations("agents");
  const { providers, isError } = useRealtimeModels();
  const switchId = useId();
  const block = value ?? null;

  const write = (next: Partial<VoiceSpec>) => {
    const merged = { ...EMPTY, ...block, ...next };
    // Rebuilt in the spec's order, whatever order the parts arrived in.
    const ordered = Object.fromEntries(
      (Object.keys(EMPTY) as (keyof VoiceSpec)[]).map((key) => [key, merged[key]]),
    ) as unknown as VoiceSpec;
    onChange(Object.values(ordered).every((part) => part === null) ? null : ordered);
  };

  return (
    <div className="space-y-4">
      <div className="flex items-start justify-between gap-4">
        <div className="space-y-0.5">
          <Label htmlFor={switchId}>{t("voiceConversationEnabled")}</Label>
          <p className="text-muted-foreground text-xs">{t("voiceConversationEnabledHint")}</p>
          {/* Said, not left as a switch that will not move. */}
          {block === null && isError && (
            <p role="alert" className="text-destructive text-xs">
              {t("voiceConversationCatalogFailed")}
            </p>
          )}
        </div>
        <Switch
          id={switchId}
          checked={block !== null}
          disabled={disabled || (block === null && providers.length === 0)}
          onCheckedChange={(on) => (on ? write(firstOf(providers[0]!)) : onChange(null))}
        />
      </div>
      {block !== null && (
        <BlockFields {...props} block={block} providers={providers} write={write} />
      )}
    </div>
  );
}

interface BlockFieldsProps extends VoiceConversationProps {
  block: VoiceSpec;
  providers: RealtimeProvider[];
  write: (next: Partial<VoiceSpec>) => void;
}

function BlockFields({ block, providers, write, disabled, ...rest }: BlockFieldsProps) {
  const t = useTranslations("agents");
  const entry = providers.find((candidate) => candidate.provider === block.provider);
  const model = modelOf(entry, block);
  return (
    <>
      <div className="grid gap-4 sm:grid-cols-2">
        <FormField label={t("voiceConversationProvider")} htmlFor="agent-voice-call-provider">
          <Select
            value={block.provider ?? undefined}
            disabled={disabled}
            onValueChange={(next) =>
              write({ ...firstOf(providers.find((c) => c.provider === next)!), secret_id: null })
            }
          >
            <SelectTrigger id="agent-voice-call-provider">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {providers.map((candidate) => (
                <SelectItem
                  key={candidate.provider}
                  value={candidate.provider}
                  textValue={candidate.name}
                >
                  <span className="flex items-center gap-2">
                    <ProviderIcon provider={candidate.provider} className="h-3.5 w-3.5" />
                    {candidate.name}
                  </span>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </FormField>
        {entry && <ModelField entry={entry} block={block} disabled={disabled} write={write} />}
        {entry?.deployment && (
          <FormField
            label={t("voiceConversationDeployment")}
            htmlFor="agent-voice-call-deployment"
            description={t("voiceConversationDeploymentHint")}
          >
            <Input
              value={block.deployment ?? ""}
              disabled={disabled}
              onChange={(event) => write({ deployment: event.target.value || null })}
            />
          </FormField>
        )}
        {entry && (
          <SpeechKeyField
            id="agent-voice-conversation-key"
            provider={entry.provider}
            providerName={entry.name}
            value={block.secret_id}
            orgVisibleOnly={false}
            kind={entry.secret_kind}
            suggestedName={t("voiceConversationKeyName", { provider: entry.name })}
            disabled={disabled}
            onChange={(secret_id) => write({ secret_id })}
          />
        )}
        {model && <VoiceField model={model} block={block} disabled={disabled} write={write} />}
        <LanguageField block={block} disabled={disabled} write={write} />
      </div>
      <LongestCall {...rest} block={block} disabled={disabled} write={write} />
      <FormField
        label={t("voiceConversationNote")}
        htmlFor="agent-voice-call-note"
        description={t("voiceConversationNoteHint")}
      >
        <Textarea
          rows={3}
          maxLength={NOTE_LIMIT}
          value={block.voice_note ?? ""}
          disabled={disabled}
          onChange={(event) => write({ voice_note: event.target.value || null })}
        />
      </FormField>
      <Limitations capabilityIds={rest.capabilityIds} hasGuardrails={rest.hasGuardrails} />
    </>
  );
}

interface PartProps {
  block: VoiceSpec;
  disabled?: boolean;
  write: (next: Partial<VoiceSpec>) => void;
}

/** The model, or for a deployment the catalog model it runs; a voice the new one lacks is replaced. */
function ModelField({ entry, block, disabled, write }: PartProps & { entry: RealtimeProvider }) {
  const t = useTranslations("agents");
  const key = entry.deployment ? "base_model" : "model";
  return (
    <FormField
      label={entry.deployment ? t("voiceConversationBaseModel") : t("voiceConversationModel")}
      htmlFor="agent-voice-call-model"
      description={entry.models.find((candidate) => candidate.id === block[key])?.description}
    >
      <Select
        value={block[key] ?? undefined}
        disabled={disabled}
        onValueChange={(next) => {
          const chosen = entry.models.find((candidate) => candidate.id === next)!;
          const keeps = block.voice !== null && chosen.voices.includes(block.voice);
          write({ [key]: next, voice: keeps ? block.voice : chosen.default_voice });
        }}
      >
        <SelectTrigger id="agent-voice-call-model">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {entry.models.map((candidate) => (
            <SelectItem key={candidate.id} value={candidate.id}>
              {candidate.name}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </FormField>
  );
}

function VoiceField({ model, block, disabled, write }: PartProps & { model: RealtimeModel }) {
  const t = useTranslations("agents");
  return (
    <FormField
      label={t("voiceConversationVoice")}
      htmlFor="agent-voice-call-voice"
      description={t("voiceConversationVoiceHint")}
    >
      <Select
        value={block.voice ?? model.default_voice}
        disabled={disabled}
        onValueChange={(voice) => write({ voice })}
      >
        <SelectTrigger id="agent-voice-call-voice">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {model.voices.map((voice) => (
            <SelectItem key={voice} value={voice}>
              {voice === model.default_voice
                ? t("voiceConversationVoiceDefault", { voice })
                : voice}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </FormField>
  );
}

function LanguageField({ block, disabled, write }: PartProps) {
  const t = useTranslations("agents");
  const { languages } = useSpeechToTextProviders();
  const languageName = useLanguageName();
  return (
    <FormField
      label={t("voiceConversationLanguage")}
      htmlFor="agent-voice-call-language"
      description={t("voiceConversationLanguageHint")}
    >
      <Select
        value={block.language ?? FOLLOW_CALLER}
        disabled={disabled}
        onValueChange={(next) => write({ language: next === FOLLOW_CALLER ? null : next })}
      >
        <SelectTrigger id="agent-voice-call-language">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={FOLLOW_CALLER}>{t("voiceConversationFollowCaller")}</SelectItem>
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
  );
}

/** Minutes as typed, kept here so a half-typed or refused value is not lost. */
function LongestCall({
  block,
  disabled,
  write,
  orgMaxSeconds,
}: PartProps & { orgMaxSeconds: number }) {
  const t = useTranslations("agents");
  const stored =
    block.max_call_seconds === null ? "" : String(Math.round(block.max_call_seconds / 60));
  const [text, setText] = useState(stored);
  if (useChanged(stored)) setText(stored);
  const minutes = Number(text.trim());
  const invalid =
    text.trim() !== "" && !(Number.isInteger(minutes) && minutes >= 1 && minutes <= MAX_MINUTES);
  const overOrg = !invalid && text.trim() !== "" && minutes * 60 > orgMaxSeconds;
  return (
    <FormField
      label={t("voiceConversationMaxLength")}
      htmlFor="agent-voice-call-max"
      description={overOrg ? undefined : t("voiceConversationMaxHint")}
      error={
        invalid
          ? t("voiceConversationMaxInvalid")
          : overOrg
            ? t("voiceConversationMaxOverOrg", { minutes: Math.floor(orgMaxSeconds / 60) })
            : null
      }
    >
      <Input
        inputMode="numeric"
        className="w-24"
        value={text}
        disabled={disabled}
        onChange={(event) => {
          const typed = event.target.value;
          setText(typed);
          const next = Number(typed.trim());
          if (typed.trim() === "") write({ max_call_seconds: null });
          else if (Number.isInteger(next) && next >= 1 && next <= MAX_MINUTES)
            write({ max_call_seconds: next * 60 });
        }}
      />
    </FormField>
  );
}

/** What a call cannot do: capabilities left out, guardrails after the fact, and no audio kept. */
function Limitations({
  capabilityIds,
  hasGuardrails,
}: {
  capabilityIds: string[];
  hasGuardrails: boolean;
}) {
  const t = useTranslations("agents");
  const { capabilities } = useCapabilityCatalog();
  const unavailable = capabilities.filter(
    (entry) => !entry.voice && capabilityIds.includes(entry.id),
  );
  return (
    <div className="space-y-2 text-xs">
      {unavailable.length > 0 && (
        <div>
          <p className="font-medium">{t("voiceConversationUnavailable")}</p>
          <ul className="text-muted-foreground mt-1 list-disc pl-5">
            {unavailable.map((entry) => (
              <li key={entry.id}>{entry.name}</li>
            ))}
          </ul>
        </div>
      )}
      {hasGuardrails && (
        <p className="bg-muted text-muted-foreground flex gap-2 rounded-lg px-3 py-2">
          <Info className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
          {t("voiceConversationGuardrails")}
        </p>
      )}
      <p className="text-muted-foreground">{t("voiceConversationRecorded")}</p>
    </div>
  );
}
