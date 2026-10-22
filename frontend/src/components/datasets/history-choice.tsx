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

interface HistoryChoiceProps {
  idPrefix: string;
  withHistory: boolean;
  onChange: (withHistory: boolean) => void;
}

/** Whether the conversation before the question comes into the case with it. */
export function HistoryChoice({ idPrefix, withHistory, onChange }: HistoryChoiceProps) {
  const t = useTranslations("datasets");
  return (
    <FormField htmlFor={`${idPrefix}-history`} label={t("historyChoice")}>
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
