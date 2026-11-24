"use client";

import { useTranslations } from "next-intl";

import { Badge, Button } from "@/components/ui";
import type { MergeFile } from "@/types/skill-merge";

/**
 * The files either side changed. A file both changed differently waits for a person to
 * keep one side - the assistant never writes a file; keeping the side it is absent from
 * drops it.
 */
export function MergeFiles({
  files,
  editable,
  saving,
  onPick,
}: {
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
          </li>
        ))}
      </ul>
    </section>
  );
}

/** What keeping a side does to the file: that side's version, or no file at all. */
function keptOf(file: MergeFile, side: "fork" | "main"): string {
  const absent = file[side] === null;
  return `${side}${absent ? "Dropped" : ""}`;
}
