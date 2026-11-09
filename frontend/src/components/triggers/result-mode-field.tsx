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

export type RoutineResultMode = "report" | "inbox";

export function ResultModeField({
  value,
  onChange,
}: {
  value: RoutineResultMode;
  onChange: (value: RoutineResultMode) => void;
}) {
  const t = useTranslations("triggers");
  return (
    <FormField
      htmlFor="routine-result-mode"
      label={t("resultMode")}
      description={t(value === "inbox" ? "resultInboxHint" : "resultReportHint")}
    >
      <Select
        value={value}
        onValueChange={(next) => {
          if (next === "report" || next === "inbox") onChange(next);
        }}
      >
        <SelectTrigger id="routine-result-mode" aria-label={t("resultMode")}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="report">{t("resultReport")}</SelectItem>
          <SelectItem value="inbox">{t("resultInbox")}</SelectItem>
        </SelectContent>
      </Select>
    </FormField>
  );
}
