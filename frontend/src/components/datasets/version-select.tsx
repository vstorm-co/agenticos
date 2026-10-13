"use client";

import { useTranslations } from "next-intl";

import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui";
import type { DatasetVersion } from "@/types/datasets";

interface VersionSelectProps {
  versions: DatasetVersion[];
  /** The version shown; null is the newest. */
  value: number | null;
  onChange: (version: number | null) => void;
}

const NEWEST = "newest";

/**
 * Which version of the dataset is on screen.
 *
 * Each entry says what that version changed, so finding "before the import" or
 * "before Tuesday's edit" does not take opening each one.
 */
export function VersionSelect({ versions, value, onChange }: VersionSelectProps) {
  const t = useTranslations("datasets");
  return (
    <Select
      value={value === null ? NEWEST : String(value)}
      onValueChange={(next) => onChange(next === NEWEST ? null : Number(next))}
    >
      <SelectTrigger className="w-64" aria-label={t("version")} data-tour="datasets-version">
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value={NEWEST}>{t("newestVersion")}</SelectItem>
        {versions.map((version) => (
          <SelectItem key={version.id} value={String(version.number)}>
            {t("versionChange", {
              number: version.number,
              change: version.change,
              count: version.changed_cases,
            })}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
