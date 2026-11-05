"use client";

import { Check, Copy } from "lucide-react";
import { useTranslations } from "next-intl";
import { useMemo, type ReactNode } from "react";

import { Button } from "@/components/ui";
import { useCodingChanges } from "@/hooks/use-coding-changes";
import { useCopyToClipboard } from "@/hooks/use-copy-to-clipboard";
import type { ChangedFile, CodingTaskChanges } from "@/lib/coding-changes-api";
import { capChangeSet, type Hunk } from "@/lib/patch";
import { cn } from "@/lib/utils";
import { CollapsibleBlock } from "../collapsible-block";

/**
 * What a coding task changed in the sandbox (#2480): the files first, then each
 * file's hunks - the part a person reviews before keeping the work.
 */
export function TaskChanges({
  changeId,
  fallback,
}: {
  changeId: string;
  /** What the panel showed before diffs - the names the harness gave - for a reader the diff is refused to. */
  fallback: ReactNode;
}) {
  const t = useTranslations("chat.tools.codingAgent");
  const { changes, isLoading, failed } = useCodingChanges(changeId);
  const diffs = useMemo(() => (changes === null ? [] : capChangeSet(changes.files)), [changes]);

  if (isLoading) return <p className="text-muted-foreground text-xs">{t("changesLoading")}</p>;
  if (failed || changes === null) {
    return (
      <>
        <p className="text-muted-foreground text-xs">{t("changesUnavailable")}</p>
        {fallback}
      </>
    );
  }
  if (changes.files.length === 0 && changes.omitted === 0) {
    return <p className="text-muted-foreground text-xs">{t("noChanges")}</p>;
  }
  const count = changes.files.length + changes.omitted;
  return (
    <CollapsibleBlock label={t("changes", { count })} open>
      <div className="space-y-3 p-3">
        <FileList changes={changes} />
        {diffs.map(({ file, hunks, hidden }) => (
          <FileDiff
            key={`${file.old_path ?? ""}:${file.path}`}
            file={file}
            hunks={hunks}
            hidden={hidden}
          />
        ))}
      </div>
    </CollapsibleBlock>
  );
}

function FileList({ changes }: { changes: CodingTaskChanges }) {
  const t = useTranslations("chat.tools.codingAgent");
  const { copy, copied } = useCopyToClipboard();
  const patch = changes.files.map((file) => file.patch ?? "").join("");
  // A file cut part way, or one past the cut with no part at all.
  const cut = changes.files.some((file) => file.truncated || file.patch === null);
  return (
    <div className="space-y-1.5">
      <ul className="space-y-0.5 text-xs">
        {changes.files.map((file) => (
          <li key={`${file.old_path ?? ""}:${file.path}`} className="flex min-w-0 gap-2">
            <span className="text-muted-foreground w-16 shrink-0">
              {t("changeStatus", { status: file.status })}
            </span>
            <span className="min-w-0 flex-1 truncate font-mono">
              {file.old_path === null
                ? file.path
                : t("renamedPath", { from: file.old_path, to: file.path })}
            </span>
            <Counts file={file} />
          </li>
        ))}
      </ul>
      {cut && <p className="text-muted-foreground text-xs italic">{t("patchCut")}</p>}
      {changes.omitted > 0 && (
        <p className="text-muted-foreground text-xs italic">
          {t("filesOmitted", { count: changes.omitted })}
        </p>
      )}
      {patch !== "" && (
        <Button
          variant="outline"
          size="sm"
          className="h-7 gap-1.5 text-xs"
          onClick={() => copy(patch)}
        >
          {copied ? (
            <Check className="size-3.5" aria-hidden />
          ) : (
            <Copy className="size-3.5" aria-hidden />
          )}
          {copied ? t("patchCopied") : t("copyPatch")}
        </Button>
      )}
    </div>
  );
}

function Counts({ file }: { file: ChangedFile }) {
  const t = useTranslations("chat.tools.codingAgent");
  if (file.binary) return <span className="text-muted-foreground shrink-0">{t("binary")}</span>;
  return (
    <span className="shrink-0 font-mono">
      <span className="text-emerald-600 dark:text-emerald-400">+{file.additions}</span>{" "}
      <span className="text-destructive">−{file.deletions}</span>
    </span>
  );
}

function FileDiff({ file, hunks, hidden }: { file: ChangedFile; hunks: Hunk[]; hidden: number }) {
  const t = useTranslations("chat.tools.codingAgent");
  // Cut before its first hunk is cut, not unchanged.
  const empty =
    file.patch === null || file.truncated
      ? t("patchOmitted")
      : file.binary
        ? t("binaryFile")
        : t("noTextChanges");
  return (
    <section className="overflow-hidden rounded-md border">
      <h4 className="bg-foreground/[0.04] truncate border-b px-3 py-1 font-mono text-xs">
        {file.path}
      </h4>
      {hunks.length === 0 ? (
        <p className="text-muted-foreground px-3 py-2 text-xs">
          {/* Lines past the change set's budget, not a file without any. */}
          {hidden > 0 ? t("moreLines", { count: hidden }) : empty}
        </p>
      ) : (
        <div className="max-h-96 overflow-auto">
          <table className="w-full border-collapse font-mono text-xs leading-5">
            <tbody>
              {hunks.map((hunk, index) => (
                <HunkRows key={index} header={hunk.header} lines={hunk.lines} />
              ))}
              {hidden > 0 && (
                <tr className="bg-muted/40">
                  <td colSpan={2} className="text-muted-foreground px-3 py-1 text-center">
                    {t("moreLines", { count: hidden })}
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

const MARK = { added: "+", removed: "−", context: "", note: "" } as const;

function HunkRows({ header, lines }: Hunk) {
  return (
    <>
      <tr className="bg-muted/60 text-muted-foreground">
        <td colSpan={2} className="px-3 py-0.5">
          {header}
        </td>
      </tr>
      {lines.map((line, index) => (
        <tr
          key={index}
          className={cn(
            line.kind === "context" && "text-muted-foreground",
            line.kind === "note" && "text-muted-foreground italic",
            line.kind === "added" && "bg-emerald-500/10",
            line.kind === "removed" && "bg-destructive/10",
          )}
        >
          <td className="text-muted-foreground w-6 px-2 py-0.5 text-center select-none">
            {MARK[line.kind]}
          </td>
          <td className="w-full py-0.5 pr-2 whitespace-pre-wrap">{line.text}</td>
        </tr>
      ))}
    </>
  );
}
