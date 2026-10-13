"use client";

import { Fragment, useMemo, useState } from "react";
import Link from "next/link";
import { ArrowRight, Ban, Globe, Info, Loader2, Plus, Server, TriangleAlert } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { toast } from "sonner";

import { SettingsSection } from "@/components/settings/settings-section";
import {
  Alert,
  AlertDescription,
  AlertTitle,
  Badge,
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
import { useModelProviders, useSpeechToTextProviders } from "@/hooks/use-model-providers";
import type { SpeechToTextProvider } from "@/hooks/use-model-providers";
import { NO_FAILURE, submitFailure, type SubmitFailure } from "@/lib/api-error";
import { ROUTES } from "@/lib/constants";
import { cn } from "@/lib/utils";
import type { DictationEngine, Organization, VoiceSettingsUpdate } from "@/types";
import type { ModelProfile } from "@/types/providers";
import { Perm } from "@/types/permissions";

/** The fields a refusal can name, so each message lands under its control. */
const FIELDS = [
  "chat_dictation",
  "speech_to_text_provider",
  "speech_to_text_model",
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
  engine: DictationEngine;
  provider: string | null;
  model: string | null;
  language: string | null;
  /** The length as typed, in `unit`. */
  amount: string;
  unit: Unit;
}

function draftOf(org: Organization): Draft {
  const seconds = org.dictation_max_seconds;
  const minutes = seconds % 60 === 0;
  return {
    engine: org.chat_dictation,
    provider: org.speech_to_text_provider,
    model: org.speech_to_text_model,
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
 * The profile a recording for `provider` is sent with, as the server picks it:
 * the first keyed profile by label, and only when there is none the first
 * keyless one that names an endpoint. `undefined` when neither exists.
 */
function profileFor(profiles: ModelProfile[], provider: string): ModelProfile | undefined {
  const own = profiles
    .filter((profile) => profile.provider === provider)
    .sort((a, b) => a.label.localeCompare(b.label));
  return (
    own.find((profile) => profile.secret_id !== null) ?? own.find((profile) => !!profile.base_url)
  );
}

/**
 * How people in this organization talk to agents: dictation in the chat today,
 * voice conversations later.
 *
 * Three engines, each saying where the audio goes, because that is the decision
 * an administrator is actually making - the browser vendor's speech service, or
 * this deployment and a provider the organization already holds credentials for.
 *
 * Rendered only for `org:settings`, which is what the PATCH checks. Hidden
 * rather than disabled, like the spending limit beside it: a section that could
 * only report a refusal is worse than no section.
 */
export function OrgVoiceSettings({ org }: { org: Organization }) {
  const { can } = usePermissions();
  // A separate component so that its catalog and profile reads are never issued
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
  if (useChanged(`${org.id}|${JSON.stringify(stored)}`)) setDraft(stored);

  const edit = (next: Partial<Draft>) => {
    setDraft((prev) => ({ ...prev, ...next }));
    setFailure(NO_FAILURE);
    setLengthInvalid(false);
  };

  const save = async () => {
    // The length is only on screen for Server; with another engine it keeps
    // whatever is stored rather than refusing on a field nobody can see.
    const seconds = draft.engine === "server" ? secondsOf(draft) : org.dictation_max_seconds;
    if (seconds === null) {
      setLengthInvalid(true);
      return;
    }
    const settings: VoiceSettingsUpdate = {
      chat_dictation: draft.engine,
      speech_to_text_language: draft.language,
      dictation_max_seconds: seconds,
    };
    // The pair only when it changed: naming it asks the server to check it
    // against the catalog, and a model withdrawn since must not stop somebody
    // switching the engine to the browser.
    if (draft.provider !== stored.provider || draft.model !== stored.model) {
      settings.speech_to_text_provider = draft.provider;
      settings.speech_to_text_model = draft.model;
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
  // Read for the path line's host alone: which providers can send is the
  // catalog's `credentialed`, answered by the server from the profiles and the
  // vault together - a vault key is invisible in the profile list.
  const { profiles } = useModelProviders();
  const form = useVoiceDraft(org);
  const { draft, failure } = form;

  // While the catalog is unread nothing is marked as lacking credentials - it is
  // empty until read, and for good when the read fails, and neither is a
  // missing credential; a provider greyed out for a frame reads as a glitch.
  const credentialed = (provider: string) =>
    providers.length === 0 ||
    (providers.find((entry) => entry.provider === provider)?.credentialed ?? false);
  const anyCredentials = providers.length === 0 || providers.some((entry) => entry.credentialed);

  const chooseEngine = (engine: DictationEngine) => {
    // Server with nothing picked yet takes the first provider that can answer,
    // so the form never sits on a choice the server would refuse. None while
    // the catalog is unread: the pair stays empty and the save names it.
    const first =
      engine === "server" && draft.provider === null
        ? providers.find((entry) => credentialed(entry.provider))
        : undefined;
    // The server drops a catalog entry with no models, so each has a first one.
    form.edit(
      first ? { engine, provider: first.provider, model: first.models[0]!.id } : { engine },
    );
  };

  return (
    <div id="org-voice" data-tour="org-voice">
      <SettingsSection title={t("voice.title")} description={t("voice.description")}>
        <h3 className="text-sm font-semibold">{t("voice.sttTitle")}</h3>
        <p className="text-muted-foreground mt-0.5 mb-4 text-sm">{t("voice.sttDescription")}</p>
        <NotReady org={org} credentialed={credentialed} providers={providers} />
        <EngineChoice
          value={draft.engine}
          serverDisabled={!anyCredentials && draft.engine !== "server"}
          error={failure.fields.chat_dictation}
          onChange={chooseEngine}
        />
        {!anyCredentials && <NoCredentials providers={providers} />}
        {draft.engine === "browser" && (
          <div className="mt-4">
            <AudioPath hops={[t("voice.pathVendor")]} note={t("voice.browserNote")} />
          </div>
        )}
        {draft.engine === "server" && (
          <ServerFields
            draft={draft}
            providers={providers}
            languages={languages}
            profiles={profiles}
            credentialed={credentialed}
            failure={failure}
            lengthInvalid={form.lengthInvalid}
            onChange={form.edit}
          />
        )}
        <DefaultFields
          draft={draft}
          providers={providers}
          languages={languages}
          profiles={profiles}
          credentialed={credentialed}
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
        <ComingSoon />
      </SettingsSection>
    </div>
  );
}

const ENGINES: { value: DictationEngine; icon: typeof Ban }[] = [
  { value: "off", icon: Ban },
  { value: "browser", icon: Globe },
  { value: "server", icon: Server },
];

interface EngineChoiceProps {
  value: DictationEngine;
  serverDisabled: boolean;
  error: string | undefined;
  onChange: (engine: DictationEngine) => void;
}

/**
 * Off, Browser or Server as three cards, each saying where the audio goes.
 *
 * Native radios inside labels: there is no radio-group primitive in `ui/`, and
 * a native group already has the arrow-key behaviour a hand-rolled one would
 * have to reimplement.
 */
function EngineChoice({ value, serverDisabled, error, onChange }: EngineChoiceProps) {
  const t = useTranslations("teams");
  return (
    <fieldset
      role="radiogroup"
      aria-label={t("voice.engineLabel")}
      aria-invalid={error ? true : undefined}
      aria-describedby={error ? "org-voice-engine-err" : undefined}
    >
      <div className="grid gap-2 sm:grid-cols-3">
        {ENGINES.map(({ value: engine, icon: Icon }) => {
          const disabled = engine === "server" && serverDisabled;
          return (
            <label
              key={engine}
              className={cn(
                "border-border bg-card focus-within:ring-ring relative grid cursor-pointer grid-cols-[auto_1fr] gap-x-2.5 gap-y-0.5 rounded-xl border p-3 transition-colors focus-within:ring-2",
                "has-[:checked]:border-foreground has-[:checked]:bg-muted",
                disabled && "cursor-not-allowed opacity-55",
              )}
            >
              <input
                type="radio"
                name="org-voice-engine"
                value={engine}
                checked={value === engine}
                disabled={disabled}
                onChange={() => onChange(engine)}
                className="pointer-events-none absolute opacity-0"
              />
              <Icon className="text-muted-foreground mt-0.5 h-4 w-4" aria-hidden />
              <span className="text-sm font-semibold">{t(`voice.engines.${engine}.label`)}</span>
              <span className="text-muted-foreground col-start-2 text-xs">
                {t(`voice.engines.${engine}.hint`)}
              </span>
            </label>
          );
        })}
      </div>
      {error && (
        <p id="org-voice-engine-err" className="text-destructive mt-2 text-xs">
          {error}
        </p>
      )}
    </fieldset>
  );
}

/** The providers as one phrase - "OpenAI, Groq or Mistral" - in the reader's language. */
function useProviderList(providers: SpeechToTextProvider[]): string {
  const locale = useLocale();
  return new Intl.ListFormat(locale, { type: "disjunction" }).format(
    providers.map((entry) => entry.name),
  );
}

/** Why Server cannot be chosen: no provider here has a key or a profile to send with. */
function NoCredentials({ providers }: { providers: SpeechToTextProvider[] }) {
  const t = useTranslations("teams");
  const names = useProviderList(providers);
  return (
    <div className="border-input mt-3 grid grid-cols-[auto_1fr] gap-x-2.5 gap-y-0.5 rounded-xl border border-dashed p-3 text-sm">
      <Server className="text-muted-foreground mt-0.5 h-4 w-4" aria-hidden />
      <strong className="font-semibold">{t("voice.noCredentialsTitle")}</strong>
      <p className="text-muted-foreground col-start-2 text-xs">
        {t("voice.noCredentialsBody", { providers: names })}
      </p>
      <Button asChild variant="outline" size="sm" className="col-start-2 mt-2 justify-self-start">
        <Link href={ROUTES.VAULT}>
          <Plus className="h-4 w-4" aria-hidden />
          {t("voice.addKey")}
        </Link>
      </Button>
    </div>
  );
}

interface NotReadyProps {
  org: Organization;
  credentialed: (provider: string) => boolean;
  providers: SpeechToTextProvider[];
}

/**
 * The stored settings ask for server dictation the chat cannot do: no pair, a
 * pair whose model the catalog has withdrawn, or a pair whose provider has lost
 * its credentials. Members then see a crossed microphone, so the person who can
 * fix it is told here.
 */
function NotReady({ org, credentialed, providers }: NotReadyProps) {
  const t = useTranslations("teams");
  if (org.chat_dictation !== "server") return null;
  // Ready means a stored pair, so the provider is only read where it is one.
  const provider = org.speech_to_text_provider as string;
  const model = org.speech_to_text_model;
  let reason: string;
  // A withdrawn model is fixed in this form; the other two need a profile.
  let needsProfile = true;
  if (!org.chat_dictation_ready) {
    // No default pair is a setup, not a fault: agents that choose their own
    // provider still dictate. Said as a note, with nothing to go and fix.
    if (model === null) {
      return (
        <Alert className="mb-4">
          <Info className="h-4 w-4" aria-hidden />
          <AlertTitle>{t("voice.agentsOnlyTitle")}</AlertTitle>
          <AlertDescription>{t("voice.agentsOnlyBody")}</AlertDescription>
        </Alert>
      );
    }
    // The server's readiness is a stored pair whose model the catalog still
    // offers, so a stored model it calls unready is one withdrawn since.
    reason = t("voice.notReadyWithdrawn", { model });
    needsProfile = false;
  } else if (credentialed(provider)) {
    return null;
  } else {
    // Only reached with the catalog read - unread, nothing lacks credentials -
    // and a ready pair is one the catalog offers, so the provider is in it.
    const name = providers.find((entry) => entry.provider === provider)!.name;
    reason = t("voice.notReadyNoCredentials", { provider: name });
  }
  return (
    <Alert variant="warning" className="mb-4">
      <TriangleAlert className="h-4 w-4" aria-hidden />
      <AlertTitle>{t("voice.notReadyTitle")}</AlertTitle>
      <AlertDescription>
        {reason}
        {needsProfile && (
          <>
            {" "}
            <Link href={ROUTES.VAULT} className="text-foreground font-medium underline">
              {t("voice.addKey")}
            </Link>
          </>
        )}
      </AlertDescription>
    </Alert>
  );
}

interface FieldsProps {
  draft: Draft;
  providers: SpeechToTextProvider[];
  languages: string[];
  profiles: ModelProfile[];
  credentialed: (provider: string) => boolean;
  failure: SubmitFailure;
  lengthInvalid: boolean;
  onChange: (next: Partial<Draft>) => void;
}

/** Where a Server recording goes, and the longest one - only for the Server engine. */
function ServerFields(props: FieldsProps) {
  const { draft, providers, profiles } = props;
  const t = useTranslations("teams");
  const chosen = providers.find((entry) => entry.provider === draft.provider);
  const host = chosen ? hostOf(profileFor(profiles, chosen.provider)?.base_url) : null;
  return (
    <div className="mt-4 space-y-4">
      {chosen && (
        <AudioPath
          hops={[
            t("voice.pathDeployment"),
            host ? t("voice.pathHost", { provider: chosen.name, host }) : chosen.name,
          ]}
          note={t("voice.pathNote", { provider: chosen.name })}
        />
      )}
      <div className="grid gap-4 sm:grid-cols-2">
        <LengthField {...props} />
      </div>
    </div>
  );
}

/**
 * The organization's default provider, model and language, whatever the engine.
 *
 * Shown for Off and Browser too, because the same pair is what a channel bot's
 * voice notes inherit: hidden there, an administrator could not see - or stop -
 * the provider a bot set to inherit is sending audio to (#1797).
 */
function DefaultFields(props: FieldsProps) {
  const { draft, providers, credentialed, failure, onChange } = props;
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
                onChange({ provider: null, model: null });
                return;
              }
              // `next` is one of the options below, and each catalog entry has a model.
              const entry = providers.find((candidate) => candidate.provider === next)!;
              onChange({ provider: next, model: entry.models[0]!.id });
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
                const usable = credentialed(entry.provider);
                const label = usable
                  ? entry.name
                  : t("voice.providerNoCredentials", { name: entry.name });
                return (
                  <SelectItem
                    key={entry.provider}
                    value={entry.provider}
                    disabled={!usable && entry.provider !== draft.provider}
                    textValue={label}
                  >
                    {label}
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
        <LanguageField {...props} />
      </div>
    </div>
  );
}

/** The host a self-hosted profile points at, for the path line. */
function hostOf(baseUrl: string | null | undefined): string | null {
  if (!baseUrl) return null;
  try {
    return new URL(baseUrl).host;
  } catch {
    return null;
  }
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

/** Where #54's voice conversations will be configured; nothing to set yet. */
function ComingSoon() {
  const t = useTranslations("teams");
  return (
    <div aria-disabled="true" className="border-border mt-6 border-t pt-5 opacity-60">
      <h3 className="flex items-center gap-2 text-sm font-semibold">
        {t("voice.conversationsTitle")}
        <Badge variant="secondary">{t("voice.comingSoon")}</Badge>
      </h3>
      <p className="text-muted-foreground mt-0.5 text-sm">{t("voice.conversationsDescription")}</p>
    </div>
  );
}
