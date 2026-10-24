"use client";

import { AlertTriangle, Plus, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";

import {
  Alert,
  AlertDescription,
  Button,
  Checkbox,
  IconButton,
  Input,
  Label,
} from "@/components/ui";
import type { TextToSpeechProvider, TextToSpeechVoice } from "@/hooks/use-model-providers";

/** One more voice the agent may speak in, as `voices` stores it. */
interface VoiceChoice {
  id: string;
  note?: string | null;
}

/** The most other voices one agent may be offered - the server's `MAX_VOICES`. */
const MAX_VOICES = 20;

/** The longest note on a voice - the server's `VoiceChoice.note` limit. */
const MAX_NOTE = 120;

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
  /**
   * What publish validation said, keyed by path within the config - `voices`,
   * `voices.0.id`. Drawn here because the generated form, which shows the rest,
   * leaves this field to this control.
   */
  errors: Readonly<Record<string, string>>;
  disabled?: boolean;
  onChange: (voices: VoiceChoice[]) => void;
}

/**
 * Which voices the agent may switch to per clip - the one limit on it.
 *
 * The usual voice is only a default. A provider's own voices are a list to tick,
 * described by the catalog; an account's voices are ids only the author knows, so
 * each is typed with a few words saying who it is - which is all the agent will
 * read about it. An empty list allows any voice, which is said as a warning: on
 * an account that includes every cloned voice in it.
 */
export function SpeechVoiceChoices({
  provider,
  offered,
  usualVoice,
  value,
  errors,
  disabled,
  onChange,
}: SpeechVoiceChoicesProps) {
  const t = useTranslations("agents");
  const full = value.length >= MAX_VOICES;

  return (
    <div className="space-y-1.5">
      <Label>{t("speechOtherVoices")}</Label>
      {provider.account_voices ? (
        <AccountVoices value={value} errors={errors} disabled={disabled} onChange={onChange} />
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
                    disabled={disabled || (full && !checked)}
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
      {errors.voices !== undefined && <p className="text-destructive text-xs">{errors.voices}</p>}
      {/* Ticked voices have no row to mark, so what publish said about one is listed here. */}
      {!provider.account_voices &&
        Object.entries(errors)
          .filter(([path]) => path.startsWith("voices."))
          .map(([path, message]) => (
            <p key={path} className="text-destructive text-xs">
              {message}
            </p>
          ))}
      {value.length === 0 && (
        <Alert variant="warning">
          <AlertTriangle className="h-4 w-4" />
          <AlertDescription>
            {provider.account_voices
              ? t("speechAnyAccountVoiceWarning", { provider: provider.name })
              : t("speechAnyVoiceWarning", { count: offered.length })}
          </AlertDescription>
        </Alert>
      )}
      <p className="text-muted-foreground text-xs">
        {full ? t("speechOtherVoicesFull", { count: MAX_VOICES }) : t("speechOtherVoicesDetail")}
      </p>
    </div>
  );
}

function AccountVoices({
  value,
  errors,
  disabled,
  onChange,
}: {
  value: VoiceChoice[];
  errors: Readonly<Record<string, string>>;
  disabled?: boolean;
  onChange: (voices: VoiceChoice[]) => void;
}) {
  const t = useTranslations("agents");
  const replace = (index: number, patch: Partial<VoiceChoice>) =>
    onChange(value.map((entry, at) => (at === index ? { ...entry, ...patch } : entry)));

  return (
    <div className="space-y-2">
      {value.map((entry, index) => {
        const idError = errors[`voices.${index}.id`];
        const noteError = errors[`voices.${index}.note`];
        return (
          <div key={index} className="space-y-1">
            <div className="flex items-center gap-2">
              <Input
                value={entry.id}
                disabled={disabled}
                aria-invalid={idError !== undefined}
                aria-label={t("speechOtherVoiceId", { position: index + 1 })}
                placeholder={t("speechVoiceIdPlaceholder")}
                onChange={(event) => replace(index, { id: event.target.value })}
              />
              <Input
                value={entry.note ?? ""}
                disabled={disabled}
                maxLength={MAX_NOTE}
                aria-invalid={noteError !== undefined}
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
            {(idError ?? noteError) !== undefined && (
              <p className="text-destructive text-xs">{idError ?? noteError}</p>
            )}
          </div>
        );
      })}
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
