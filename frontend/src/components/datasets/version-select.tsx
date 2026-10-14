"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import {
  Input,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import type { DatasetVersion } from "@/types/datasets";

interface VersionSelectProps {
  /** The newest versions, newest first; the list may stop short of version 1. */
  versions: DatasetVersion[];
  /** The newest version's number. Versions are numbered 1 to it with no gaps. */
  latest: number;
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
export function VersionSelect({ versions, latest, value, onChange }: VersionSelectProps) {
  const t = useTranslations("datasets");
  const oldestListed = versions.at(-1)?.number ?? 1;
  const unlisted = value !== null && !versions.some((version) => version.number === value);
  const [typed, setTyped] = useState("");

  function goTo() {
    const number = Number(typed);
    if (Number.isInteger(number) && number >= 1 && number <= latest) onChange(number);
    setTyped("");
  }

  return (
    <div className="flex items-center gap-2">
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
          {unlisted && (
            <SelectItem value={String(value)}>{t("versionNumber", { number: value })}</SelectItem>
          )}
        </SelectContent>
      </Select>
      {oldestListed > 1 && (
        // The list holds the newest versions only; an older one is reached by number.
        <Input
          type="number"
          min={1}
          max={latest}
          className="w-36"
          aria-label={t("olderVersion")}
          placeholder={t("olderVersion")}
          value={typed}
          onChange={(event) => setTyped(event.target.value)}
          onKeyDown={(event) => {
            if (event.key === "Enter") goTo();
          }}
          onBlur={() => typed !== "" && goTo()}
        />
      )}
    </div>
  );
}
