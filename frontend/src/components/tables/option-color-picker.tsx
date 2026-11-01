"use client";

import { useTranslations } from "next-intl";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui";
import type { OptionColor } from "@/types/tables";

import { OPTION_TONES } from "@/lib/table-option-colors";
const COLORS: OptionColor[] = ["gray", "blue", "green", "yellow", "purple", "red"];

export function OptionColorPicker({
  label,
  value,
  onChange,
}: {
  label: string;
  value?: OptionColor | null;
  onChange: (value: OptionColor | null) => void;
}) {
  const t = useTranslations("tables.defaults");
  return (
    <Select
      value={value ?? "auto"}
      onValueChange={(color) => onChange(COLORS.find((entry) => entry === color) ?? null)}
    >
      <SelectTrigger aria-label={t("optionColor", { name: label })} className="w-32 shrink-0">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value="auto">{t("colors.auto")}</SelectItem>
        {COLORS.map((color) => (
          <SelectItem key={color} value={color}>
            <span className={`inline-flex rounded px-1.5 py-0.5 ${OPTION_TONES[color]}`}>
              {t(`colors.${color}`)}
            </span>
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
