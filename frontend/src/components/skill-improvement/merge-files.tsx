"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { Badge, Button } from "@/components/ui";
import { formatBytes } from "@/lib/utils";
import type { MergeFile } from "@/types/skill-merge";
import { MergeFileDiff, type FileSide, type SideVersions } from "./merge-file-diff";

/**
 * The files either side changed. A file both changed differently waits for a person to
 * keep one side - the assistant never writes a file; keeping the side it is absent from
 * drops it.
 */
export function MergeFiles({
  skillId,
  versions,
  files,
  editable,
  saving,
  onPick,
}: {
  skillId: string;
  versions: SideVersions;
  files: MergeFile[];
  editable: boolean;
  saving: boolean;
  onPick: (name: string, take: "fork" | "main") => void;
}) {
  const t = useTranslations("skillImprovement.merge");
  const changed = files.filter((file) => file.state !== "same");
  if (changed.length === 0) return null;
  return (
    <section aria-label={t("files")} className="space-y-2">
      <h3 className="text-sm font-medium">{t("files")}</h3>
      <ul className="divide-y rounded-lg border text-sm">
        {changed.map((file) => (
          <li key={file.name} className="flex flex-wrap items-center gap-2 p-3">
            <span className="font-mono text-xs">{file.name}</span>
            <Badge variant={file.take === null ? "destructive" : "outline"}>
              {t(`state.${file.state}`)}
            </Badge>
            <span className="text-muted-foreground text-xs">
              {file.take === null ? t("fileOpen") : t(`kept.${keptOf(file, file.take)}`)}
            </span>
            {editable && file.state === "conflict" && (
              <span className="ml-auto flex gap-2">
                {(["fork", "main"] as const).map((side) => (
                  <Button
                    key={side}
                    size="sm"
                    variant={file.take === side ? "default" : "outline"}
                    aria-pressed={file.take === side}
                    disabled={saving}
                    onClick={() => onPick(file.name, side)}
                  >
                    {t(`take.${keptOf(file, side)}`)}
                  </Button>
                ))}
              </span>
            )}
            <FileDetails skillId={skillId} versions={versions} file={file} />
          </li>
        ))}
      </ul>
    </section>
  );
}

/** Each side's version of the file as its manifest describes it, and what changed on opening. */
function FileDetails({
  skillId,
  versions,
  file,
}: {
  skillId: string;
  versions: SideVersions;
  file: MergeFile;
}) {
  const t = useTranslations("skillImprovement.merge.file");
  const [open, setOpen] = useState(false);
  return (
    <div className="basis-full space-y-2">
      <ul className="text-muted-foreground space-y-0.5 text-xs">
        {(["base", "fork", "main"] as FileSide[]).map((side) => {
          const entry = file[side];
          return (
            <li key={side} className="flex flex-wrap gap-x-2">
              <span>
                {entry === null
                  ? t("absent", { side })
                  : t("side", { side, size: formatBytes(entry.size_bytes) })}
              </span>
              {entry?.description && (
                <span className="min-w-0 break-words">{entry.description}</span>
              )}
            </li>
          );
        })}
      </ul>
      <Button
        size="sm"
        variant="ghost"
        aria-expanded={open}
        onClick={() => setOpen((shown) => !shown)}
      >
        {t(open ? "hide" : "show")}
      </Button>
      {open && <MergeFileDiff skillId={skillId} versions={versions} file={file} />}
    </div>
  );
}

/** What keeping a side does to the file: that side's version, or no file at all. */
function keptOf(file: MergeFile, side: "fork" | "main"): string {
  const absent = file[side] === null;
  return `${side}${absent ? "Dropped" : ""}`;
}
