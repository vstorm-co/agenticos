"use client";

import { useTranslations } from "next-intl";

import {
  Input,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { lengthFields, type CheckDraft, type LengthFields, type LengthUnit } from "./case-form";

const UNITS: LengthUnit[] = ["characters", "words"];

/** A length check's fields: what it counts, the least and the most, and where in a JSON answer. */
export function LengthValue({
  check,
  number,
  disabled,
  onChange,
}: {
  check: CheckDraft;
  number: number;
  disabled: boolean;
  onChange: (patch: Partial<CheckDraft>) => void;
}) {
  const t = useTranslations("datasets.lengthCheck");
  const fields = lengthFields(check);
  const set = (patch: Partial<LengthFields>) => onChange({ rest: { ...fields, ...patch } });
  return (
    <div className="flex min-w-0 flex-1 flex-wrap gap-2">
      <Select
        value={fields.unit}
        disabled={disabled}
        onValueChange={(unit) => set({ unit: unit as LengthUnit })}
      >
        <SelectTrigger className="w-32" aria-label={t("unit", { number })}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {UNITS.map((unit) => (
            <SelectItem key={unit} value={unit}>
              {t(`units.${unit}`)}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
      <Input
        className="w-24"
        inputMode="numeric"
        disabled={disabled}
        value={fields.min}
        aria-label={t("min", { number })}
        placeholder={t("minPlaceholder")}
        onChange={(event) => set({ min: event.target.value })}
      />
      <Input
        className="w-24"
        inputMode="numeric"
        disabled={disabled}
        value={check.value}
        aria-label={t("max", { number })}
        placeholder={t("maxPlaceholder")}
        onChange={(event) => onChange({ value: event.target.value })}
      />
      <Input
        className="min-w-32 flex-1"
        disabled={disabled}
        value={fields.path}
        aria-label={t("path", { number })}
        placeholder={t("pathPlaceholder")}
        onChange={(event) => set({ path: event.target.value })}
      />
    </div>
  );
}
