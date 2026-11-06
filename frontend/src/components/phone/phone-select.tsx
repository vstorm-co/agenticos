"use client";
import { useId } from "react";
import { useTranslations } from "next-intl";
import {
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import type { PhoneChoice } from "@/lib/phone-api";
export function PhoneSelect({
  label,
  value,
  onChange,
  choices,
  optional = false,
  disabled = false,
}: {
  label: string;
  value: string;
  onChange: (value: string) => void;
  choices: PhoneChoice[];
  optional?: boolean;
  disabled?: boolean;
}) {
  const id = useId();
  const t = useTranslations("phone");
  return (
    <div className="space-y-1">
      <Label htmlFor={id}>{label}</Label>
      <Select
        value={value || "none"}
        onValueChange={(next) => onChange(next === "none" ? "" : next)}
        disabled={disabled}
      >
        <SelectTrigger id={id}>
          <SelectValue placeholder={t("choose")} />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="none" disabled={!optional}>
            {optional ? t("none") : t("choose")}
          </SelectItem>
          {choices.map((choice) => (
            <SelectItem key={choice.id} value={choice.id}>
              {choice.label}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}
