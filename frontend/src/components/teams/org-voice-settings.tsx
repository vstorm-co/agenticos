"use client";

import { Fragment, useMemo, useState } from "react";
import { ArrowRight, Loader2, TriangleAlert } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { toast } from "sonner";

import { SettingsSection } from "@/components/settings/settings-section";
import { OrgVoiceUsage } from "@/components/teams/org-voice-usage";
import { ProviderIcon } from "@/components/vault/provider-icon";
import { SpeechKeyField, useSpeechKeyCheck } from "@/components/vault/speech-key-field";
import {
  Alert,
  AlertDescription,
  AlertTitle,
  Button,
  Input,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { FormField } from "@/components/ui/form-field";
import { useOrganizations, usePermissions } from "@/hooks";
import { useChanged } from "@/hooks/use-changed";
import { useSpeechToTextProviders } from "@/hooks/use-model-providers";
import type { SpeechToTextProvider } from "@/hooks/use-model-providers";
import { NO_FAILURE, submitFailure, type SubmitFailure } from "@/lib/api-error";
import type { Organization, VoiceSettingsUpdate } from "@/types";
import { Perm } from "@/types/permissions";

/** The fields a refusal can name, so each message lands under its control. */
const FIELDS = [
  "speech_to_text_provider",
  "speech_to_text_model",
  "speech_to_text_secret_id",
  "speech_to_text_language",
  "dictation_max_seconds",
] as const;

/** Radix `SelectItem` refuses `""`, so auto-detect needs a value of its own. */
const AUTO_DETECT = "auto";
/** The same for "no default provider", which clears the pair. */
const NO_PROVIDER = "none";
const MIN_SECONDS = 10;
const MAX_SECONDS = 600;

type Unit = "s" | "min";

interface Draft {
  provider: string | null;
  model: string | null;
  /** The organization-wide vault key the pair is sent with. */
  secretId: string | null;
  language: string | null;
  /** The length as typed, in `unit`. */
  amount: string;
  unit: Unit;
}

function draftOf(org: Organization): Draft {
  const seconds = org.dictation_max_seconds;
  const minutes = seconds % 60 === 0;
  return {
    provider: org.speech_to_text_provider,
    model: org.speech_to_text_model,
    secretId: org.speech_to_text_secret_id,
    language: org.speech_to_text_language,
    amount: String(minutes ? seconds / 60 : seconds),
    unit: minutes ? "min" : "s",
  };
}

/** The typed length in seconds, or `null` when it is not one the server takes. */
function secondsOf(draft: Draft): number | null {
  const value = Number(draft.amount.trim());
  if (draft.amount.trim() === "" || !Number.isFinite(value)) return null;
  const seconds = draft.unit === "min" ? value * 60 : value;
  return seconds >= MIN_SECONDS && seconds <= MAX_SECONDS ? Math.round(seconds) : null;
}

/**
 * The organization's speech-to-text default: the provider, model, key and
 * language agents and channel bots inherit when they transcribe with a
 * provider, and the longest dictation.
 *
 * No switch for dictation or calls: those are each agent's (#54). The chat's
 * microphone uses the browser's own recognition unless an agent's Dictation
 * switch sends it to a provider, which is the pair chosen here or its own.
 *
 * Rendered only for `org:settings`, which is what the PATCH checks. Hidden
 * rather than disabled, like the spending limit beside it: a section that could
 * only report a refusal is worse than no section.
 */
export function OrgVoiceSettings({ org }: { org: Organization }) {
  const { can } = usePermissions();
  // A separate component so that its catalog and vault reads are never issued
  // for somebody who may not change them.
  return can(Perm.orgSettings) ? <VoiceForm org={org} /> : null;
}

/**
 * The card's draft, and saving it.
 *
 * One form and one Save, as in the spending limit: the five settings are
 * validated together on the server, so saving them one control at a time would
 * refuse half-made choices (a provider before its model) that the next click
 * would have completed.
 */
function useVoiceDraft(org: Organization) {
  const t = useTranslations("teams");
  const tErrors = useTranslations("errors");
  const { setVoiceSettings } = useOrganizations();
  const stored = draftOf(org);
  const [draft, setDraft] = useState(stored);
  const [failure, setFailure] = useState<SubmitFailure>(NO_FAILURE);
  const [lengthInvalid, setLengthInvalid] = useState(false);
  const [saving, setSaving] = useState(false);

  // Re-seed when the stored settings change underneath - another tab, or this
  // form's own save coming back with what the server settled on. During
  // render: an effect would show the old values for a frame first.
  if (useChanged(`${org.id}|${JSON.stringify(stored)}`)) {
    setDraft(stored);
  }

  const edit = (next: Partial<Draft>) => {
    setDraft((prev) => ({ ...prev, ...next }));
    setFailure(NO_FAILURE);
    setLengthInvalid(false);
  };

  const save = async () => {
    const seconds = secondsOf(draft);
    if (seconds === null) {
      setLengthInvalid(true);
      return;
    }
    const settings: VoiceSettingsUpdate = {
      speech_to_text_language: draft.language,
      dictation_max_seconds: seconds,
    };
    // The pair and its key only when one changed: naming them asks the server
    // to check them against the catalog and the vault, and a model withdrawn
    // since must not stop somebody changing the language. All three together,
    // because the key is checked against the provider.
    if (
      draft.provider !== stored.provider ||
      draft.model !== stored.model ||
      draft.secretId !== stored.secretId
    ) {
      settings.speech_to_text_provider = draft.provider;
      settings.speech_to_text_model = draft.model;
      settings.speech_to_text_secret_id = draft.secretId;
    }
    setSaving(true);
    try {
      await setVoiceSettings(org.id, settings);
      toast.success(t("voice.saved"));
    } catch (error) {
      const problem = submitFailure(error, { fields: FIELDS }, tErrors);
      setFailure(problem);
      if (problem.toast) toast.error(problem.toast);
    } finally {
      setSaving(false);
    }
  };

  return {
    draft,
    edit,
    reset: () => {
      setDraft(stored);
      setFailure(NO_FAILURE);
      setLengthInvalid(false);
    },
    dirty: JSON.stringify(draft) !== JSON.stringify(stored),
    failure,
    lengthInvalid,
    saving,
    save,
  };
}

function VoiceForm({ org }: { org: Organization }) {
  const t = useTranslations("teams");
  const { providers, languages } = useSpeechToTextProviders();
  // Only organization-wide keys: the platform spends this one for everybody.
  const hasKey = useSpeechKeyCheck(true);
  const form = useVoiceDraft(org);
  const { draft, failure } = form;

  return (
    <div id="org-voice" data-tour="org-voice">
      <SettingsSection title={t("voice.title")} description={t("voice.description")}>
        <h3 className="text-sm font-semibold">{t("voice.sttTitle")}</h3>
        <p className="text-muted-foreground mt-0.5 mb-4 text-sm">{t("voice.sttDescription")}</p>
        <OrgVoiceUsage />
        <NotReady org={org} providers={providers} />
        <DefaultFields
          draft={draft}
          providers={providers}
          languages={languages}
          hasKey={hasKey}
          failure={failure}
          lengthInvalid={form.lengthInvalid}
          onChange={form.edit}
        />
        <div className="mt-5 flex justify-end gap-2">
          <Button
            variant="ghost"
            size="sm"
            disabled={!form.dirty || form.saving}
            onClick={form.reset}
          >
            {t("voice.cancel")}
          </Button>
          <Button size="sm" disabled={!form.dirty || form.saving} onClick={() => void form.save()}>
            {form.saving && <Loader2 className="h-4 w-4 animate-spin" aria-hidden />}
            {t("voice.save")}
          </Button>
        </div>
      </SettingsSection>
    </div>
  );
}

interface NotReadyProps {
  org: Organization;
  providers: SpeechToTextProvider[];
}

/**
 * The stored default cannot transcribe: a pair with no key named for it (never
 * chosen, or deleted since), or a model the catalog has withdrawn. Every agent
 * and bot that inherits it then falls back to the browser or stays silent, so
 * the person who can fix it is told here - and it is fixed in this form.
 */
function NotReady({ org, providers }: NotReadyProps) {
  const t = useTranslations("teams");
  const model = org.speech_to_text_model;
  if (model === null) return null;
  // A stored model means a stored provider - the pair is both or neither.
  const provider = org.speech_to_text_provider as string;
  const entry = providers.find((candidate) => candidate.provider === provider);
  // Unread catalog: nothing is known yet, so nothing is claimed.
  if (entry === undefined && providers.length === 0) return null;
  let reason: string | null = null;
  if (org.speech_to_text_secret_id === null) {
    reason = t("voice.notReadyNoKey", { provider: entry?.name ?? provider });
  } else if (!entry?.models.some((candidate) => candidate.id === model)) {
    reason = t("voice.notReadyWithdrawn", { model });
  }
  if (reason === null) return null;
  return (
    <Alert variant="warning" className="mb-4">
      <TriangleAlert className="h-4 w-4" aria-hidden />
      <AlertTitle>{t("voice.notReadyTitle")}</AlertTitle>
      <AlertDescription>{reason}</AlertDescription>
    </Alert>
  );
}

interface FieldsProps {
  draft: Draft;
  providers: SpeechToTextProvider[];
  languages: string[];
  hasKey: (provider: string) => boolean;
  failure: SubmitFailure;
  lengthInvalid: boolean;
  onChange: (next: Partial<Draft>) => void;
}

/**
 * The organization's default provider, model, key, language and longest
 * recording, and where a recording sent to that provider travels.
 */
function DefaultFields(props: FieldsProps) {
  const { draft, providers, hasKey, failure, onChange } = props;
  const t = useTranslations("teams");
  const chosen = providers.find((entry) => entry.provider === draft.provider);
  return (
    <div className="mt-6">
      <h3 className="text-sm font-semibold">{t("voice.defaultTitle")}</h3>
      <p className="text-muted-foreground mt-0.5 mb-4 text-sm">{t("voice.defaultDescription")}</p>
      <div className="grid gap-4 sm:grid-cols-2">
        <FormField
          label={t("voice.provider")}
          htmlFor="org-voice-provider"
          description={t("voice.providerHint")}
          error={failure.fields.speech_to_text_provider}
        >
          <Select
            value={draft.provider ?? NO_PROVIDER}
            onValueChange={(next) => {
              if (next === NO_PROVIDER) {
                onChange({ provider: null, model: null, secretId: null });
                return;
              }
              // `next` is one of the options below, and each catalog entry has a
              // model. The key was the old provider's, so it goes with it.
              const entry = providers.find((candidate) => candidate.provider === next)!;
              onChange({ provider: next, model: entry.models[0]!.id, secretId: null });
            }}
          >
            <SelectTrigger id="org-voice-provider">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={NO_PROVIDER} textValue={t("voice.providerNone")}>
                {t("voice.providerNone")}
              </SelectItem>
              {providers.map((entry) => {
                const label = hasKey(entry.provider)
                  ? entry.name
                  : t("voice.providerNoKey", { name: entry.name });
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
        {chosen && (
          <FormField
            label={t("voice.model")}
            htmlFor="org-voice-model"
            description={t("voice.modelHint", { provider: chosen.name })}
            error={failure.fields.speech_to_text_model}
          >
            <Select value={draft.model ?? undefined} onValueChange={(model) => onChange({ model })}>
              <SelectTrigger id="org-voice-model">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {chosen.models.map((model) => (
                  <SelectItem key={model.id} value={model.id} textValue={model.name}>
                    {model.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FormField>
        )}
        {chosen && (
          <SpeechKeyField
            id="org-voice-key"
            provider={chosen.provider}
            providerName={chosen.name}
            value={draft.secretId}
            orgVisibleOnly
            error={failure.fields.speech_to_text_secret_id}
            onChange={(secretId) => onChange({ secretId })}
          />
        )}
        <LanguageField {...props} />
        <LengthField {...props} />
      </div>
      {chosen && (
        <div className="mt-4">
          <AudioPath
            hops={[t("voice.pathDeployment"), chosen.name]}
            note={t("voice.pathNote", { provider: chosen.name })}
          />
        </div>
      )}
    </div>
  );
}

/**
 * Where a recording travels from the browser - to the browser vendor, or through
 * this deployment to the provider - and a note on what that means.
 */
function AudioPath({ hops, note }: { hops: string[]; note: string }) {
  const t = useTranslations("teams");
  const hop =
    "bg-card border-border inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5";
  return (
    <div className="bg-muted flex flex-wrap items-center gap-1.5 rounded-xl px-3 py-2.5 text-xs">
      <span className={hop}>{t("voice.pathBrowser")}</span>
      {hops.map((label) => (
        <Fragment key={label}>
          <ArrowRight className="text-muted-foreground h-3.5 w-3.5" aria-hidden />
          <span className={hop}>{label}</span>
        </Fragment>
      ))}
      <p className="text-muted-foreground mt-1 basis-full">{note}</p>
    </div>
  );
}

function LanguageField({ draft, languages, failure, onChange }: FieldsProps) {
  const t = useTranslations("teams");
  const locale = useLocale();
  const options = useMemo(() => {
    // `fallback: "code"` answers a code it cannot name with the code itself.
    const names = new Intl.DisplayNames([locale], { type: "language", fallback: "code" });
    return languages
      .map((code) => ({
        code,
        label: t("voice.languageOption", { name: names.of(code)!, code }),
      }))
      .sort((a, b) => a.label.localeCompare(b.label, locale));
  }, [languages, locale, t]);
  return (
    <FormField
      label={t("voice.language")}
      htmlFor="org-voice-language"
      // Mistral publishes neither Whisper's language list nor its accepted formats.
      description={
        draft.provider === "mistral" ? t("voice.languageHintMistral") : t("voice.languageHint")
      }
      error={failure.fields.speech_to_text_language}
    >
      <Select
        value={draft.language ?? AUTO_DETECT}
        onValueChange={(next) => onChange({ language: next === AUTO_DETECT ? null : next })}
      >
        <SelectTrigger id="org-voice-language">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={AUTO_DETECT} textValue={t("voice.languageAuto")}>
            {t("voice.languageAuto")}
          </SelectItem>
          {options.map((option) => (
            <SelectItem key={option.code} value={option.code} textValue={option.label}>
              {option.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </FormField>
  );
}

/**
 * The longest recording, as a number and a unit.
 *
 * Laid out by hand rather than through `FormField`, which labels its one child:
 * here the label belongs to the number, and the unit beside it names itself.
 */
function LengthField({ draft, failure, lengthInvalid, onChange }: FieldsProps) {
  const t = useTranslations("teams");
  const error = lengthInvalid
    ? t("voice.maxLengthInvalid")
    : (failure.fields.dictation_max_seconds ?? null);
  return (
    <div className="space-y-1.5">
      <Label htmlFor="org-voice-max">{t("voice.maxLength")}</Label>
      <div className="flex gap-2">
        <Input
          id="org-voice-max"
          inputMode="numeric"
          className="w-24"
          value={draft.amount}
          aria-invalid={error ? true : undefined}
          aria-describedby={error ? "org-voice-max-err" : "org-voice-max-desc"}
          onChange={(event) => onChange({ amount: event.target.value })}
        />
        <Select value={draft.unit} onValueChange={(unit) => onChange({ unit: unit as Unit })}>
          <SelectTrigger className="w-32" aria-label={t("voice.unit")}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="s">{t("voice.seconds")}</SelectItem>
            <SelectItem value="min">{t("voice.minutes")}</SelectItem>
          </SelectContent>
        </Select>
      </div>
      {error ? (
        <p id="org-voice-max-err" className="text-destructive text-xs leading-relaxed">
          {error}
        </p>
      ) : (
        <p id="org-voice-max-desc" className="text-muted-foreground text-xs leading-relaxed">
          {t("voice.maxLengthHint")}
        </p>
      )}
    </div>
  );
}
