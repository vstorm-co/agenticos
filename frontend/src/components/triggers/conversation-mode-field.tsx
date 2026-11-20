"use client";

import { useTranslations } from "next-intl";

import {
  FormField,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import type { TriggerConversationMode } from "@/types/triggers";

const MODES: TriggerConversationMode[] = ["continue", "fresh"];

/**
 * Which conversation a fire's run goes in (#14).
 *
 * The caption says what the chosen mode costs, because each one trades
 * something: continuing keeps every fire in one run log the trigger's Runs
 * tab can read, while a fresh conversation per fire keeps one fire from
 * reading the previous fires' turns - and leaves the Runs tab with no one
 * conversation to list.
 */
export function ConversationModeField({
  value,
  onChange,
}: {
  value: TriggerConversationMode;
  onChange: (value: TriggerConversationMode) => void;
}) {
  const t = useTranslations("triggers");
  return (
    <FormField
      label={t("conversationModeLabel")}
      htmlFor="trigger-conversation-mode"
      description={t(`conversationModeHint.${value}`)}
    >
      <Select value={value} onValueChange={(next) => onChange(next as TriggerConversationMode)}>
        <SelectTrigger id="trigger-conversation-mode">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {MODES.map((mode) => (
            <SelectItem key={mode} value={mode}>
              {t(`conversationMode.${mode}`)}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </FormField>
  );
}
