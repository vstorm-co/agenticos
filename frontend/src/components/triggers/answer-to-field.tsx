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
import type { TriggerAnswerTo } from "@/types/triggers";

/**
 * Where each fire's answer is delivered to its person (#2575).
 *
 * The run log keeps every fire either way. `primary` also puts the answer in the person's own
 * conversation with the agent, so one chat holds everything the agent tells them; a routine
 * made for one particular chat (`conversation`) is shown as such and kept, not silently
 * rewritten by an edit that did not touch it.
 */
export function AnswerToField({
  value,
  onChange,
}: {
  value: TriggerAnswerTo;
  onChange: (value: TriggerAnswerTo) => void;
}) {
  const t = useTranslations("triggers");
  const options: TriggerAnswerTo[] =
    value === "conversation" ? ["primary", "run_log", "conversation"] : ["primary", "run_log"];
  return (
    <FormField
      label={t("answerToLabel")}
      htmlFor="trigger-answer-to"
      description={t(`answerToHint.${value}`)}
    >
      <Select value={value} onValueChange={(next) => onChange(next as TriggerAnswerTo)}>
        <SelectTrigger id="trigger-answer-to">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {options.map((option) => (
            <SelectItem key={option} value={option}>
              {t(`answerTo.${option}`)}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </FormField>
  );
}
