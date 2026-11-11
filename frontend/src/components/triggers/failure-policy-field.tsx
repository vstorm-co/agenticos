"use client";

import { useTranslations } from "next-intl";
import { useId } from "react";

import {
  Badge,
  FormField,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";

export function FailurePolicyField({
  value,
  onChange,
  disabled = false,
}: {
  value: number | null;
  onChange: (value: number | null) => void;
  disabled?: boolean;
}) {
  const t = useTranslations("routineHealth");
  const id = useId();
  return (
    <FormField label={t("label")} htmlFor={id} description={t("hint")}>
      <Select
        disabled={disabled}
        value={value === null ? "off" : String(value)}
        onValueChange={(next) => {
          if (next === "off") {
            onChange(null);
            return;
          }
          const count = Number(next);
          if (Number.isInteger(count) && count >= 1 && count <= 20) onChange(count);
        }}
      >
        <SelectTrigger id={id}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="off">{t("off")}</SelectItem>
          {Array.from({ length: 20 }, (_, index) => index + 1).map((count) => (
            <SelectItem key={count} value={String(count)}>
              {t("after", { count })}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </FormField>
  );
}

export function RoutineAutoPause({
  stoppedAt,
  count,
}: {
  stoppedAt: string | null | undefined;
  count: number | undefined;
}) {
  const t = useTranslations("routineHealth");
  return stoppedAt ? <Badge variant="secondary">{t("paused", { count: count ?? 0 })}</Badge> : null;
}
