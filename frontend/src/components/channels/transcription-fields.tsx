"use client";

import {
  FormField,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { useSpeechToTextProviders } from "@/hooks/use-model-providers";
import { useTranslations } from "next-intl";

/** The value the picker edits: both halves, or neither. */
export interface TranscriptionChoice {
  provider: string | null;
  model: string | null;
}

export const TRANSCRIPTION_OFF = "off";
/**
 * What "do not transcribe" is worth in a Radix select.
 *
 * `SelectItem` refuses an empty string as a value - it uses one to mean "nothing
 * selected" - so the off state needs a sentinel here and is mapped back to a pair
 * of nulls before it is sent.
 */

interface TranscriptionFieldsProps {
  value: TranscriptionChoice;
  onChange: (next: TranscriptionChoice) => void;
  /** Prefix for the input ids, so two of these on one page do not collide. */
  idPrefix: string;
}

/**
 * Which model transcribes this bot's voice messages, if any.
 *
 * Shared by the add and edit dialogs, unlike the credential fields beside them:
 * those mean different things in the two places - set a value against replace one
 * that is never read back - and this means exactly one thing in both.
 *
 * **Both halves move together.** A provider with no model has nothing to call and
 * a model with no provider has nowhere to send it, so choosing a provider takes
 * its first model and choosing "off" clears both. The server enforces the same
 * rule against the stored row; this is what stops somebody meeting it.
 *
 * Absent when the deployment offers nothing - every provider it knows wants a
 * service account, say - because an empty picker is a control that reads as a
 * choice somebody failed to make.
 */
export function TranscriptionFields({ value, onChange, idPrefix }: TranscriptionFieldsProps) {
  const t = useTranslations("pages.channels");
  const { providers } = useSpeechToTextProviders();

  if (providers.length === 0) return null;

  const chosen = providers.find((entry) => entry.provider === value.provider);

  return (
    <div className="grid gap-4 sm:grid-cols-2">
      <FormField
        label={t("transcriptionProvider")}
        htmlFor={`${idPrefix}-stt-provider`}
        description={t("transcriptionProviderHint")}
      >
        <Select
          value={value.provider ?? TRANSCRIPTION_OFF}
          onValueChange={(next) => {
            if (next === TRANSCRIPTION_OFF) {
              onChange({ provider: null, model: null });
              return;
            }
            const entry = providers.find((candidate) => candidate.provider === next);
            onChange({ provider: next, model: entry?.models[0]?.id ?? null });
          }}
        >
          <SelectTrigger id={`${idPrefix}-stt-provider`}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={TRANSCRIPTION_OFF} textValue={t("transcriptionOff")}>
              {t("transcriptionOff")}
            </SelectItem>
            {providers.map((entry) => (
              <SelectItem key={entry.provider} value={entry.provider} textValue={entry.name}>
                {entry.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </FormField>

      {chosen !== undefined && (
        <FormField
          label={t("transcriptionModel")}
          htmlFor={`${idPrefix}-stt-model`}
          description={
            chosen.models.find((model) => model.id === value.model)?.description ??
            t("transcriptionModelHint")
          }
        >
          <Select
            value={value.model ?? ""}
            onValueChange={(next) => onChange({ provider: chosen.provider, model: next })}
          >
            <SelectTrigger id={`${idPrefix}-stt-model`}>
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
    </div>
  );
}
