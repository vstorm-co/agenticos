"use client";

import { useMemo, useState } from "react";
import { useTranslations } from "next-intl";

import { useWideScreen } from "@/hooks/use-wide-screen";
import {
  type DiffLine,
  type FoldedLines,
  type WordPart,
  diffLines,
  diffWords,
  foldUnchanged,
} from "@/lib/diff";
import { cn } from "@/lib/utils";

type Mode = "unified" | "split";
type Shown = DiffLine | (FoldedLines & { at: number });

/** A changed line's words, the changed ones marked as removed or added for every reader. */
function Words({ parts, kind }: { parts: WordPart[]; kind: "added" | "removed" }) {
  return parts.map((part, index) =>
    !part.changed ? (
      <span key={index}>{part.text}</span>
    ) : kind === "added" ? (
      <ins key={index} className="rounded-sm bg-emerald-500/30 no-underline">
        {part.text}
      </ins>
    ) : (
      <del key={index} className="bg-destructive/25 rounded-sm no-underline">
        {part.text}
      </del>
    ),
  );
}

/**
 * The surroundings of a passage as rows of their own: a stored boundary need not
 * fall on a newline, and a heading must not read as part of the changed line.
 */
function unchanged(text: string): DiffLine[] {
  return text
    ? text
        .replace(/\n$/, "")
        .split("\n")
        .map((line) => ({ kind: "same" as const, text: line }))
    : [];
}

/** Each removed line paired with the added line that replaced it, for word highlights. */
function pairWords(lines: DiffLine[]): Map<DiffLine, WordPart[]> {
  const words = new Map<DiffLine, WordPart[]>();
  for (let index = 0; index < lines.length;) {
    const removed: DiffLine[] = [];
    while (lines[index]?.kind === "removed") removed.push(lines[index++]!);
    const added: DiffLine[] = [];
    while (lines[index]?.kind === "added") added.push(lines[index++]!);
    removed.forEach((line, at) => {
      const partner = added[at];
      if (!partner) return;
      const pair = diffWords(line.text, partner.text);
      words.set(line, pair.before);
      words.set(partner, pair.after);
    });
    if (!removed.length && !added.length) index++;
  }
  return words;
}

function LineText({ line, words }: { line: DiffLine; words: Map<DiffLine, WordPart[]> }) {
  const parts = words.get(line);
  return parts && line.kind !== "same" ? <Words parts={parts} kind={line.kind} /> : line.text;
}

function Sign({ kind }: { kind: DiffLine["kind"] }) {
  const t = useTranslations("authoring.diff");
  if (kind === "same") return null;
  return (
    <>
      <span aria-hidden>
        {/* i18n-exempt: diff gutter glyphs, the SpecDiff convention */}
        {kind === "added" ? "+" : "−"}
      </span>
      <span className="sr-only">{t(kind)}</span>
    </>
  );
}

const ROW = {
  same: "text-muted-foreground",
  added: "bg-emerald-500/10",
  removed: "bg-destructive/10",
};

/**
 * A text change read the way a code review reads one: removed and added lines,
 * the changed words marked inside them, a few unchanged lines around each change
 * and the rest folded. Side by side is offered on a wide screen only.
 */
export function DiffView({
  before,
  after,
  context = "",
  trailing = "",
  emptyLabel,
}: {
  before: string;
  after: string;
  /** Text before the changed passage, shown unchanged. */
  context?: string;
  /** Text after the changed passage, shown unchanged. */
  trailing?: string;
  /** Said when both sides are empty. */
  emptyLabel?: string;
}) {
  const t = useTranslations("authoring.diff");
  const wide = useWideScreen();
  const [chosen, setChosen] = useState<Mode>("unified");
  const [opened, setOpened] = useState<Set<number>>(new Set());
  const lines = useMemo(
    () => [...unchanged(context), ...diffLines(before, after), ...unchanged(trailing)],
    [before, after, context, trailing],
  );
  const words = useMemo(() => pairWords(lines), [lines]);
  // Nothing changed is still worth reading whole; there is no change to fold around.
  const folded = useMemo(
    () => (lines.some((line) => line.kind !== "same") ? foldUnchanged(lines) : lines),
    [lines],
  );
  const mode = wide ? chosen : "unified";
  if (!before && !after && emptyLabel)
    return <p className="text-muted-foreground text-xs">{emptyLabel}</p>;
  const shown = folded.flatMap<Shown>((item, at) =>
    item.kind !== "fold" ? [item] : opened.has(at) ? item.lines : [{ ...item, at }],
  );
  const fold = (item: FoldedLines & { at: number }, span: number) => (
    <tr key={`fold-${item.at}`}>
      <td colSpan={span} className="bg-muted/40 py-0.5 text-center">
        <button
          type="button"
          className="text-muted-foreground text-xs underline underline-offset-2"
          onClick={() => setOpened(new Set([...opened, item.at]))}
        >
          {t("showUnchanged", { count: item.lines.length })}
        </button>
      </td>
    </tr>
  );
  return (
    <div className="space-y-1">
      {wide && (
        <div role="group" aria-label={t("view")} className="flex justify-end gap-1">
          {(["unified", "split"] as const).map((value) => (
            <button
              key={value}
              type="button"
              aria-pressed={mode === value}
              className={cn(
                "rounded px-2 py-0.5 text-xs",
                mode === value ? "bg-muted font-medium" : "text-muted-foreground",
              )}
              onClick={() => setChosen(value)}
            >
              {t(value)}
            </button>
          ))}
        </div>
      )}
      <div className="max-h-96 overflow-auto rounded-md border">
        <table className="w-full table-fixed border-collapse font-mono text-xs leading-5">
          <tbody>
            {mode === "unified"
              ? shown.map((item, index) =>
                  item.kind === "fold" ? (
                    fold(item, 2)
                  ) : (
                    <tr key={index} className={ROW[item.kind]}>
                      <td className="text-muted-foreground w-6 px-1 py-0.5 text-center align-top select-none">
                        <Sign kind={item.kind} />
                      </td>
                      <td className="py-0.5 pr-2 break-words whitespace-pre-wrap">
                        <LineText line={item} words={words} />
                      </td>
                    </tr>
                  ),
                )
              : splitRows(shown).map((row, index) =>
                  "fold" in row ? (
                    fold(row.fold, 4)
                  ) : (
                    <tr key={index}>
                      {[row.left, row.right].map((line, side) => (
                        <SplitCell key={side} line={line} words={words} />
                      ))}
                    </tr>
                  ),
                )}
          </tbody>
        </table>
      </div>
    </div>
  );
}

function SplitCell({
  line,
  words,
}: {
  line: DiffLine | undefined;
  words: Map<DiffLine, WordPart[]>;
}) {
  return (
    <>
      <td
        className={cn(
          "text-muted-foreground w-6 border-l px-1 py-0.5 text-center align-top select-none first:border-l-0",
          line && ROW[line.kind],
        )}
      >
        {line && <Sign kind={line.kind} />}
      </td>
      <td
        className={cn(
          "w-1/2 py-0.5 pr-2 align-top break-words whitespace-pre-wrap",
          line && ROW[line.kind],
        )}
      >
        {line && <LineText line={line} words={words} />}
      </td>
    </>
  );
}

type SplitRow = { left?: DiffLine; right?: DiffLine } | { fold: FoldedLines & { at: number } };

/** Unchanged lines on both sides, and each block of removals beside the additions after it. */
function splitRows(shown: Shown[]): SplitRow[] {
  const rows: SplitRow[] = [];
  for (let index = 0; index < shown.length;) {
    const item = shown[index]!;
    if (item.kind === "fold") {
      rows.push({ fold: item });
      index++;
      continue;
    }
    if (item.kind === "same") {
      rows.push({ left: item, right: item });
      index++;
      continue;
    }
    const removed: DiffLine[] = [];
    while ((shown[index] as DiffLine | undefined)?.kind === "removed")
      removed.push(shown[index++] as DiffLine);
    const added: DiffLine[] = [];
    while ((shown[index] as DiffLine | undefined)?.kind === "added")
      added.push(shown[index++] as DiffLine);
    for (let at = 0; at < Math.max(removed.length, added.length); at++)
      rows.push({ left: removed[at], right: added[at] });
  }
  return rows;
}
