"use client";

import { useTranslations } from "next-intl";

import { FormField, Input } from "@/components/ui";

/** The end-time control uses the person's device clock; the API always receives an offset. */
export function endInput(instant: string | null | undefined): string {
  if (!instant) return "";
  const date = new Date(instant);
  const pad = (value: number) => String(value).padStart(2, "0");
  return `${date.getFullYear()}-${pad(date.getMonth() + 1)}-${pad(date.getDate())}T${pad(date.getHours())}:${pad(date.getMinutes())}`;
}

/** Blank removes the limit; invalid or nonexistent local times remain an error. */
export function endInstant(value: string): string | null | undefined {
  if (!value) return null;
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return undefined;
  const instant = date.toISOString();
  return endInput(instant) === value ? instant : undefined;
}

export function EndsAtField({
  value,
  onChange,
  invalid,
  disabled = false,
}: {
  value: string;
  onChange: (value: string) => void;
  invalid: boolean;
  disabled?: boolean;
}) {
  const t = useTranslations("triggers");
  return (
    <FormField
      label={t("endsAtLabel")}
      htmlFor="trigger-ends-at"
      description={t("endsAtHint", { zone: Intl.DateTimeFormat().resolvedOptions().timeZone })}
      error={invalid ? t("endsAtInvalid") : undefined}
    >
      <Input
        id="trigger-ends-at"
        type="datetime-local"
        step="60"
        disabled={disabled}
        value={value}
        aria-invalid={invalid}
        onChange={(event) => onChange(event.target.value)}
      />
    </FormField>
  );
}
