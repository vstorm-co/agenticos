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
import type { RoutineChatMode } from "@/types/triggers";

/** Whether each execution has an editable chat or shares a read-only history. */
export function ChatModeField({
  value,
  onChange,
}: {
  value: RoutineChatMode;
  onChange: (value: RoutineChatMode) => void;
}) {
  const t = useTranslations("triggers");
  const options: RoutineChatMode[] = ["per_run", "shared"];
  return (
    <FormField
      label={t("chatModeLabel")}
      htmlFor="trigger-chat-mode"
      description={t(`chatModeHint.${value}`)}
    >
      <Select
        value={value}
        onValueChange={(next) => {
          if (next === "per_run" || next === "shared") onChange(next);
        }}
      >
        <SelectTrigger id="trigger-chat-mode">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {options.map((option) => (
            <SelectItem key={option} value={option}>
              {t(`chatMode.${option}`)}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </FormField>
  );
}
