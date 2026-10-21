"use client";

import { Plus, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button, Checkbox, IconButton, Input, Label } from "@/components/ui";
import type { TextToSpeechProvider, TextToSpeechVoice } from "@/hooks/use-model-providers";

/** One more voice the agent may speak in, as `voices` stores it. */
export interface VoiceChoice {
  id: string;
  note?: string | null;
}

/** The most other voices one agent may be offered - the server's `MAX_VOICES`. */
export const MAX_VOICES = 20;

/** The stored `voices`, read defensively: a hand-written spec may hold anything. */
export function storedVoices(value: unknown): VoiceChoice[] {
  if (!Array.isArray(value)) return [];
  return value.filter(
    (entry): entry is VoiceChoice =>
      typeof entry === "object" && entry !== null && typeof entry.id === "string",
  );
}

interface SpeechVoiceChoicesProps {
  provider: TextToSpeechProvider;
  /** The chosen model's own voices; empty on a provider whose voices are the account's. */
  offered: TextToSpeechVoice[];
  /** The voice the agent speaks in unless it chooses another; not offered twice. */
  usualVoice: string;
  value: VoiceChoice[];
  disabled?: boolean;
  onChange: (voices: VoiceChoice[]) => void;
}

/**
 * Which other voices the agent may choose per clip.
 *
 * A provider's own voices are a list to tick, described by the catalog. An
 * account's voices are ids only the author knows, so each is typed with a few
 * words saying who it is - which is all the agent will read about it.
 */
export function SpeechVoiceChoices({
  provider,
  offered,
  usualVoice,
  value,
  disabled,
  onChange,
}: SpeechVoiceChoicesProps) {
  const t = useTranslations("agents");

  return (
    <div className="space-y-1.5">
      <Label>{t("speechOtherVoices")}</Label>
      {provider.account_voices ? (
        <AccountVoices value={value} disabled={disabled} onChange={onChange} />
      ) : (
        <div className="grid gap-1.5 sm:grid-cols-2">
          {offered
            .filter((voice) => voice.id !== usualVoice)
            .map((voice) => {
              const checked = value.some((entry) => entry.id === voice.id);
              return (
                <label key={voice.id} className="flex items-center gap-2 text-sm">
                  <Checkbox
                    checked={checked}
                    disabled={disabled}
                    onCheckedChange={() =>
                      onChange(
                        checked
                          ? value.filter((entry) => entry.id !== voice.id)
                          : [...value, { id: voice.id }],
                      )
                    }
                  />
                  {voice.name}
                </label>
              );
            })}
        </div>
      )}
      <p className="text-muted-foreground text-xs">{t("speechOtherVoicesDetail")}</p>
    </div>
  );
}

function AccountVoices({
  value,
  disabled,
  onChange,
}: {
  value: VoiceChoice[];
  disabled?: boolean;
  onChange: (voices: VoiceChoice[]) => void;
}) {
  const t = useTranslations("agents");
  const replace = (index: number, patch: Partial<VoiceChoice>) =>
    onChange(value.map((entry, at) => (at === index ? { ...entry, ...patch } : entry)));

  return (
    <div className="space-y-2">
      {value.map((entry, index) => (
        <div key={index} className="flex items-center gap-2">
          <Input
            value={entry.id}
            disabled={disabled}
            aria-label={t("speechOtherVoiceId", { position: index + 1 })}
            placeholder={t("speechVoiceIdPlaceholder")}
            onChange={(event) => replace(index, { id: event.target.value })}
          />
          <Input
            value={entry.note ?? ""}
            disabled={disabled}
            maxLength={120}
            aria-label={t("speechOtherVoiceNote", { position: index + 1 })}
            placeholder={t("speechOtherVoiceNotePlaceholder")}
            onChange={(event) => replace(index, { note: event.target.value || null })}
          />
          <IconButton
            variant="ghost"
            disabled={disabled}
            aria-label={t("speechOtherVoiceRemove", { position: index + 1 })}
            onClick={() => onChange(value.filter((_, at) => at !== index))}
          >
            <Trash2 className="h-4 w-4" />
          </IconButton>
        </div>
      ))}
      <Button
        type="button"
        variant="outline"
        size="sm"
        disabled={disabled || value.length >= MAX_VOICES}
        onClick={() => onChange([...value, { id: "" }])}
      >
        <Plus className="h-4 w-4" />
        {t("speechOtherVoiceAdd")}
      </Button>
    </div>
  );
}
