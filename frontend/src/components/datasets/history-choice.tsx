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
import { followsOn, type AskedBefore } from "./follows-on";

interface HistoryChoiceProps {
  idPrefix: string;
  withHistory: boolean;
  onChange: (withHistory: boolean) => void;
  /** The question, when known, so one that plainly follows on is pointed out. */
  asked?: AskedBefore;
}

/** Whether the conversation before the question comes into the case with it. */
export function HistoryChoice({ idPrefix, withHistory, onChange, asked }: HistoryChoiceProps) {
  const t = useTranslations("datasets");
  return (
    <FormField
      htmlFor={`${idPrefix}-history`}
      label={t("historyChoice")}
      description={
        asked !== undefined && followsOn(asked.question) ? t("historyFollowUp") : undefined
      }
    >
      <Select
        value={withHistory ? "with" : "alone"}
        onValueChange={(next) => onChange(next === "with")}
      >
        <SelectTrigger id={`${idPrefix}-history`}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="alone">{t("historyAlone")}</SelectItem>
          <SelectItem value="with">{t("historyWith")}</SelectItem>
        </SelectContent>
      </Select>
    </FormField>
  );
}
