"use client";

import { Shrink } from "lucide-react";
import { useTranslations } from "next-intl";

import type { Compaction } from "@/types";

interface CompactionNoticeProps {
  /** The summary in flight, or `null` when none is. */
  compacting: Compaction | null;
}

/**
 * Says the agent is summarising its own history, while it is doing it.
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
 */
export function CompactionNotice({ compacting }: CompactionNoticeProps) {
  const t = useTranslations("chat");
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
