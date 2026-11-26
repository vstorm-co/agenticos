"use client";

import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { DiffView } from "@/components/authoring/diff-view";
import { Button, Skeleton } from "@/components/ui";
import { useSkillVersionFile } from "@/hooks/use-skill-proposal-baseline";
import { getErrorMessage } from "@/lib/api-error";
import { saveBlob } from "@/lib/file-access";
import { getSkillVersionFile } from "@/lib/skill-versions-api";
import type { MergeFile } from "@/types/skill-merge";

/** Larger than this, a side is offered as a download rather than compared on screen. */
export const COMPARE_LIMIT_BYTES = 200 * 1024;

export type FileSide = "base" | "fork" | "main";

/** The version each side of the merge reads its files from. */
export type SideVersions = Record<FileSide, string>;

/** The sides that changed the file, each compared with where both started. */
function changedSides(file: MergeFile): ("fork" | "main")[] {
  if (file.state === "conflict") return ["fork", "main"];
  return file.state === "main" ? ["main"] : ["fork"];
}

/**
 * What each side did to one file, read when a person opens it: a diff from where
 * both sides started, or a download of each side for a file too large to compare
 * here or one that is not text.
 */
export function MergeFileDiff({
  skillId,
  versions,
  file,
}: {
  skillId: string;
  versions: SideVersions;
  file: MergeFile;
}) {
  const t = useTranslations("skillImprovement.merge.file");
  const tErrors = useTranslations("errors");
  const common = useTranslations("common");
  const changed = changedSides(file);
  const shown = (["base", ...changed] as FileSide[]).filter((side) => file[side] !== null);
  const tooLarge = shown.some((side) => file[side]!.size_bytes > COMPARE_LIMIT_BYTES);
  const read = (side: FileSide) => (shown.includes(side) && !tooLarge ? versions[side] : null);
  const reads = {
    base: useSkillVersionFile(skillId, read("base"), file.name),
    fork: useSkillVersionFile(skillId, read("fork"), file.name),
    main: useSkillVersionFile(skillId, read("main"), file.name),
  };
  const text = (side: FileSide) => reads[side].data?.content ?? "";
  const download = async (side: FileSide) => {
    try {
      const { content } = await getSkillVersionFile(skillId, versions[side], file.name);
      saveBlob(new Blob([content], { type: "text/plain" }), file.name.split("/").pop()!);
    } catch (failure) {
      toast.error(getErrorMessage(failure, tErrors));
    }
  };
  const downloads = (reason: string) => (
    <div className="space-y-2">
      <p className="text-muted-foreground text-xs">{reason}</p>
      <div className="flex flex-wrap gap-2">
        {shown.map((side) => (
          <Button key={side} size="sm" variant="outline" onClick={() => void download(side)}>
            {t("download", { side })}
          </Button>
        ))}
      </div>
    </div>
  );

  if (tooLarge) return downloads(t("tooLarge"));
  const failed = shown.map((side) => reads[side]).filter((one) => one.error !== null);
  if (failed.length > 0)
    return (
      <div role="alert" className="flex flex-wrap items-center gap-2">
        <p className="text-destructive min-w-0 flex-1 text-xs">
          {t("readFailed", { reason: getErrorMessage(failed[0]!.error, tErrors) })}
        </p>
        <Button
          size="sm"
          variant="outline"
          onClick={() => failed.forEach((one) => void one.refetch())}
        >
          {common("retry")}
        </Button>
      </div>
    );
  if (shown.some((side) => reads[side].isLoading)) return <Skeleton className="h-24 w-full" />;
  // A NUL byte is how text tools tell a binary file; a diff of one is noise.
  if (shown.some((side) => text(side).includes("\u0000"))) return downloads(t("notText"));
  return (
    <div className="space-y-3">
      {changed.map((side) => (
        <div key={side} className="min-w-0 space-y-1">
          <p className="text-muted-foreground text-xs">{t("compare", { side })}</p>
          <DiffView before={text("base")} after={text(side)} />
        </div>
      ))}
    </div>
  );
}
