"use client";

import { Shrink, TriangleAlert } from "lucide-react";
import { useTranslations } from "next-intl";

import type { Compaction } from "@/types";

interface CompactionNoticeProps {
  /** The summary in flight, or `null` when none is. */
  compacting: Compaction | null;
  /**
   * A window whose fixed overhead is already past the trigger, or `null`.
   *
   * Not a state — a setting. No summary can get under an overhead that is not in
   * the history, so the platform does nothing rather than buy one on every
   * request for ever; and doing nothing is indistinguishable on screen from a
   * setting that works. This is that silence given a voice.
   */
  impossible?: Compaction | null;
}

/**
 * Says the agent is summarising its own history — or why it cannot.
 *
 * Compaction happens between two of a turn's model requests, where nothing else
 * streams — and a summary is a whole request of its own, over a history that is
 * by definition long. Without this the chat stops dead for the length of it: no
 * token arrives, no tool step opens, and the only honest reading of the screen is
 * that something has broken. That is what makes somebody reload the page, which
 * cancels the turn and loses the summary they were waiting for.
 *
 * It sits above the composer rather than in the transcript because it is not
 * something the agent *said* — nothing here is persisted, and a reopened
 * conversation must not find a step describing plumbing.
 *
 * Only the summarising strategy reaches this. The ones that edit a list and
 * return would be a notice that appeared and vanished within a frame.
 *
 * The warning takes precedence when nothing is running, and is displaced the
 * moment something is: a summary that ran is the answer to it.
 */
export function CompactionNotice({ compacting, impossible = null }: CompactionNoticeProps) {
  const t = useTranslations("chat");
  if (compacting === null && impossible !== null) {
    return (
      <div
        className="mb-2 flex items-center gap-2 px-1 text-xs text-amber-600"
        role="status"
        aria-live="polite"
      >
        <TriangleAlert className="h-3 w-3" aria-hidden />
        {t("compactionImpossible", {
          overhead: impossible.overhead_tokens ?? 0,
          window: impossible.window_tokens ?? 0,
        })}
      </div>
    );
  }
  if (compacting === null) return null;

  return (
    <div
      className="text-muted-foreground mb-2 flex items-center gap-2 px-1 text-xs"
      role="status"
      aria-live="polite"
    >
      <Shrink className="h-3 w-3 animate-pulse" aria-hidden />
      {compacting.messages_before === null
        ? t("compacting")
        : t("compactingCount", { count: compacting.messages_before })}
    </div>
  );
}
