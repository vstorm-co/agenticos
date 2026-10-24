"use client";

import { Check, LoaderCircle, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { useEffect, useState } from "react";

import { cn, formatElapsed } from "@/lib/utils";

import type { NodeRunState, NodeRunSummary } from "./run-overlay";

/** Each state's word, from the run page's own step statuses. */
const WORD: Record<NodeRunState, string> = {
  pending: "pending",
  starting: "starting",
  running: "running",
  waiting: "waiting",
  done: "succeeded",
  failed: "failed",
  attention: "needs_attention",
  skipped: "skipped",
  notReached: "notReached",
};

// Solid fills - a tint mixed into the card, never a see-through one - since the
// pill sits on the card's border, which would otherwise show through it.
const LOOK: Record<NodeRunState, string> = {
  pending:
    "bg-[color-mix(in_oklch,var(--color-warning)_12%,var(--color-card))] text-warning border-warning/40",
  starting:
    "bg-[color-mix(in_oklch,var(--color-success)_15%,var(--color-card))] text-success border-success/40",
  running: "bg-success text-background border-transparent",
  waiting:
    "bg-[var(--domain-build-subtle)] text-[var(--domain-build)] border-[var(--domain-build-line)]",
  done: "bg-[color-mix(in_oklch,var(--color-success)_12%,var(--color-card))] text-success border-success/35",
  failed: "bg-destructive text-destructive-foreground border-transparent",
  attention: "bg-destructive text-destructive-foreground border-transparent",
  skipped: "bg-muted text-muted-foreground border-border",
  notReached: "bg-muted text-muted-foreground border-border",
};

/**
 * What a step did in a run, on its card's top-right corner - where it reads at
 * a glance and keeps out of the card's own content. A step done says how long
 * it took.
 */
export function RunPill({
  state,
  summary,
}: {
  state: NodeRunState;
  summary: NodeRunSummary | null;
}) {
  const t = useTranslations("pages.workflows.nodeStatus");
  const took = state === "done" && summary?.durationMs != null ? summary.durationMs : null;
  return (
    <span
      data-run-state={state}
      className={cn(
        "absolute -top-2.5 right-2.5 z-10 inline-flex items-center gap-1 rounded-full border px-2 text-[0.6875rem] leading-[1.125rem] font-semibold whitespace-nowrap",
        LOOK[state],
      )}
    >
      {(state === "running" || state === "starting") && (
        <LoaderCircle aria-hidden="true" className="size-3 animate-spin" />
      )}
      {state === "done" && <Check aria-hidden="true" className="size-3" />}
      {(state === "failed" || state === "attention") && <X aria-hidden="true" className="size-3" />}
      {took === null ? t(WORD[state]) : formatElapsed(took)}
      {state === "running" && summary?.startedAt != null && <Ticking since={summary.startedAt} />}
    </span>
  );
}

/** How often a running step's timer moves on. */
const TICK_MS = 100;

/**
 * How long a running step has been going, counting up from when the server
 * says it started. A clock behind the server's would start below zero: it
 * shows nothing until it catches up.
 */
function Ticking({ since }: { since: string }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), TICK_MS);
    return () => clearInterval(timer);
  }, []);
  const elapsed = now - Date.parse(since);
  if (elapsed < 0) return null;
  return <span className="tabular-nums">{`· ${formatElapsed(elapsed)}`}</span>;
}
