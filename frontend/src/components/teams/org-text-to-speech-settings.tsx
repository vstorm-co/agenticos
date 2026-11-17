"use client";

import { useState } from "react";
import { Volume2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { ServiceCard } from "@/components/settings/service-card";
import { SpeechKeyField } from "@/components/vault/speech-key-field";
import {
  Button,
  FormField,
  Input,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Switch,
} from "@/components/ui";
import { useOrganizations } from "@/hooks";
import { useChanged } from "@/hooks/use-changed";
import { useTextToSpeechProviders } from "@/hooks/use-model-providers";
import { useUnsavedChanges } from "@/hooks/use-unsaved-changes";
import { submitFailure } from "@/lib/api-error";
import type { Organization, OrganizationTextToSpeech } from "@/types";

interface Draft {
  enabled: boolean;
  provider: string;
  model: string;
  voice: string;
  secretId: string | null;
}

function draftOf(value: OrganizationTextToSpeech | null | undefined): Draft {
  return {
    enabled: value?.enabled ?? false,
    provider: value?.provider ?? "",
    model: value?.model ?? "",
    voice: value?.voice ?? "",
    secretId: value?.secret_id ?? null,
  };
}

/** Its parent checks org:settings before mounting the catalog or vault readers. */
export function OrgTextToSpeechSettings({
  org,
}: {
  org: Pick<Organization, "id" | "text_to_speech">;
}) {
  const t = useTranslations("teams.voice");
  const errors = useTranslations("errors");
  const { setVoiceSettings } = useOrganizations();
  const { providers, isError } = useTextToSpeechProviders();
  const stored = draftOf(org.text_to_speech);
  const [draft, setDraft] = useState(stored);
  const [saving, setSaving] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  const [forceOpen, setForceOpen] = useState(false);
  if (useChanged(`${org.id}|${JSON.stringify(stored)}`)) {
    setDraft(stored);
    setFailure(null);
  }
  const dirty = JSON.stringify(draft) !== JSON.stringify(stored);
  const provider = providers.find((entry) => entry.provider === draft.provider);
  const model = provider?.models.find((entry) => entry.id === draft.model);
  const edit = (next: Partial<Draft>) => {
    setDraft((current) => ({ ...current, ...next }));
    setFailure(null);
  };
  const reset = () => {
    setDraft(stored);
    setFailure(null);
  };

  const save = async (): Promise<boolean> => {
    const complete = Boolean(draft.provider && draft.model && draft.secretId);
    if (draft.enabled && !complete) {
      setFailure(t("tts.required"));
      return false;
    }
    setSaving(true);
    try {
      await setVoiceSettings(org.id, {
        text_to_speech:
          complete && draft.secretId
            ? {
                enabled: draft.enabled,
                provider: draft.provider,
                model: draft.model,
                voice: draft.voice.trim() || null,
                secret_id: draft.secretId,
              }
            : null,
      });
      toast.success(t("saved"));
      setFailure(null);
      return true;
    } catch (error) {
      const problem = submitFailure(error, { fields: ["text_to_speech"] }, errors);
      setFailure(problem.fields.text_to_speech ?? null);
      if (problem.toast) toast.error(problem.toast);
      return false;
    } finally {
      setSaving(false);
    }
  };
  useUnsavedChanges(`org-tts:${org.id}`, { dirty, save, discard: reset });

  return (
    <ServiceCard
      icon={Volume2}
      title={t("tts.title")}
      description={t("tts.description")}
      collapsible
      open={forceOpen}
      onOpenChange={setForceOpen}
      action={
        <Switch
          aria-label={t("tts.title")}
          checked={draft.enabled}
          disabled={saving}
          onCheckedChange={(enabled) => {
            edit({ enabled });
            setForceOpen(true);
          }}
        />
      }
    >
      <fieldset disabled={saving} className="space-y-4">
        {failure && (
          <p role="alert" className="text-destructive text-sm">
            {failure}
          </p>
        )}
        {isError && (
          <p role="status" className="text-destructive text-sm">
            {t("tts.catalogUnavailable")}
          </p>
        )}
        <div className="grid gap-4 sm:grid-cols-2">
          <FormField htmlFor="org-tts-provider" label={t("provider")}>
            <Select
              value={draft.provider}
              onValueChange={(id) => {
                const next = providers.find((entry) => entry.provider === id);
                const first = next?.models[0];
                edit({
                  provider: id,
                  model: first?.id ?? "",
                  voice: first?.voices[0]?.id ?? "",
                  secretId: null,
                });
              }}
            >
              <SelectTrigger id="org-tts-provider">
                <SelectValue placeholder={t("providerNone")} />
              </SelectTrigger>
              <SelectContent>
                {draft.provider && !provider && (
                  <SelectItem value={draft.provider} disabled>
                    {draft.provider}
                  </SelectItem>
                )}
                {providers.map((entry) => (
                  <SelectItem key={entry.provider} value={entry.provider}>
                    {entry.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FormField>
          <FormField htmlFor="org-tts-model" label={t("model")}>
            <Select
              value={draft.model}
              disabled={!provider}
              onValueChange={(id) => {
                const next = provider?.models.find((entry) => entry.id === id);
                edit({
                  model: id,
                  voice:
                    next?.voices.some((entry) => entry.id === draft.voice) ||
                    provider?.account_voices
                      ? draft.voice
                      : (next?.voices[0]?.id ?? ""),
                });
              }}
            >
              <SelectTrigger id="org-tts-model">
                <SelectValue placeholder={t("providerNone")} />
              </SelectTrigger>
              <SelectContent>
                {draft.model && !model && (
                  <SelectItem value={draft.model} disabled>
                    {draft.model}
                  </SelectItem>
                )}
                {provider?.models.map((entry) => (
                  <SelectItem key={entry.id} value={entry.id}>
                    {entry.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </FormField>
        </div>
        <FormField htmlFor="org-tts-voice" label={t("tts.voice")}>
          {provider?.account_voices ? (
            <Input
              id="org-tts-voice"
              value={draft.voice}
              onChange={(event) => edit({ voice: event.target.value })}
            />
          ) : (
            <Select
              value={draft.voice}
              disabled={!model}
              onValueChange={(voice) => edit({ voice })}
            >
              <SelectTrigger id="org-tts-voice">
                <SelectValue placeholder={t("providerNone")} />
              </SelectTrigger>
              <SelectContent>
                {draft.voice && !model?.voices.some((entry) => entry.id === draft.voice) && (
                  <SelectItem value={draft.voice} disabled>
                    {draft.voice}
                  </SelectItem>
                )}
                {model?.voices.map((entry) => (
                  <SelectItem key={entry.id} value={entry.id}>
                    {entry.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          )}
        </FormField>
        {provider && (
          <SpeechKeyField
            id="org-tts-key"
            provider={provider.provider}
            providerName={provider.name}
            value={draft.secretId}
            onChange={(secretId) => edit({ secretId })}
            orgVisibleOnly
          />
        )}
        <div className="flex justify-end gap-2">
          <Button variant="ghost" disabled={!dirty || saving} onClick={reset}>
            {t("cancel")}
          </Button>
          <Button disabled={!dirty || saving} onClick={() => void save()}>
            {t("save")}
          </Button>
        </div>
      </fieldset>
    </ServiceCard>
  );
}
