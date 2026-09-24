"use client";

import { useFormatter, useTranslations } from "next-intl";

import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui";
import type { ArtifactVersion } from "@/types/artifact";

/** Stands for "whatever is newest" in the select, which a version id never is. */
const CURRENT = "current";

interface VersionPickerProps {
  /** The kept versions, newest first. */
  versions: ArtifactVersion[];
  /** The version shown, or null for the current one. */
  value: string | null;
  onChange: (versionId: string | null) => void;
}

/**
 * Which version the frame shows.
 *
 * "Latest" rather than the newest number, so a page left open follows the next
 * publication; a number pins what a conversation pointed at. A version that was
 * pruned since the link was made is not in the list, and the frame says so.
 */
export function VersionPicker({ versions, value, onChange }: VersionPickerProps) {
  const t = useTranslations("artifacts");
  const format = useFormatter();
  if (versions.length < 2 && value === null) return null;
  return (
    <Select
      value={value ?? CURRENT}
      onValueChange={(next) => onChange(next === CURRENT ? null : next)}
    >
      <SelectTrigger className="w-56" aria-label={t("version")}>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value={CURRENT}>{t("latestVersion")}</SelectItem>
        {versions.map((version) => (
          <SelectItem key={version.id} value={version.id}>
            {t("versionOption", {
              version: version.number,
              when: format.dateTime(new Date(version.created_at), {
                dateStyle: "medium",
                timeStyle: "short",
              }),
            })}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}
