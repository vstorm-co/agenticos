"use client";

import { ChevronDown, History } from "lucide-react";
import { useFormatter, useLocale, useTranslations } from "next-intl";

import {
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuLabel,
  DropdownMenuRadioGroup,
  DropdownMenuRadioItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@/components/ui";
import { formatBytes, timeAgo } from "@/lib/utils";
import type { ArtifactVersion } from "@/types/artifact";

/** Stands for "whatever is newest" in the menu, which a version id never is. */
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
 *
 * A menu rather than a select, because a version is more than its number: when
 * it was published, how large it is, and whether it is the newest - which a
 * select could only fit as one run-on line of text.
 */
export function VersionPicker({ versions, value, onChange }: VersionPickerProps) {
  const t = useTranslations("artifacts");
  const tTime = useTranslations("time");
  const locale = useLocale();
  const format = useFormatter();
  if (versions.length < 2 && value === null) return null;

  const newest = versions[0];
  const shown = value === null ? newest : versions.find((version) => version.id === value);

  return (
    <DropdownMenu>
      <DropdownMenuTrigger asChild>
        <Button
          size="sm"
          variant="outline"
          aria-label={t("version")}
          className="gap-1.5 font-normal"
        >
          <History className="text-muted-foreground h-3.5 w-3.5" aria-hidden />
          {shown !== undefined && (
            <span className="font-medium tabular-nums">
              {t("versionNumber", { version: shown.number })}
            </span>
          )}
          {value === null && (
            <span className="text-muted-foreground hidden sm:inline">{t("latestShort")}</span>
          )}
          <ChevronDown className="text-muted-foreground h-3.5 w-3.5" aria-hidden />
        </Button>
      </DropdownMenuTrigger>
      <DropdownMenuContent align="end" className="w-72">
        <DropdownMenuLabel className="text-muted-foreground text-xs font-medium">
          {t("versions")}
        </DropdownMenuLabel>
        <DropdownMenuRadioGroup
          value={value ?? CURRENT}
          onValueChange={(next) => onChange(next === CURRENT ? null : next)}
        >
          <DropdownMenuRadioItem value={CURRENT} className="py-2">
            <span className="flex flex-col">
              <span>{t("latestVersion")}</span>
              <span className="text-muted-foreground text-xs">{t("latestVersionHint")}</span>
            </span>
          </DropdownMenuRadioItem>
          <DropdownMenuSeparator />
          <div className="max-h-72 overflow-y-auto">
            {versions.map((version) => {
              const published = new Date(version.created_at);
              return (
                <DropdownMenuRadioItem
                  key={version.id}
                  value={version.id}
                  className="gap-3 py-2"
                  title={format.dateTime(published, { dateStyle: "medium", timeStyle: "short" })}
                >
                  <span className="w-8 shrink-0 font-medium tabular-nums">
                    {t("versionNumber", { version: version.number })}
                  </span>
                  <span className="text-muted-foreground min-w-0 flex-1 truncate text-xs">
                    {timeAgo(version.created_at, tTime, locale)}
                  </span>
                  {version.id === newest?.id ? (
                    <span className="bg-muted text-foreground shrink-0 rounded px-1.5 py-0.5 text-[10px] font-medium">
                      {t("currentTag")}
                    </span>
                  ) : (
                    <span className="text-muted-foreground shrink-0 text-xs tabular-nums">
                      {formatBytes(version.size_bytes)}
                    </span>
                  )}
                </DropdownMenuRadioItem>
              );
            })}
          </div>
        </DropdownMenuRadioGroup>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
