"use client";

import { useLocale } from "next-intl";

import { formatDateTimeSeconds } from "@/lib/utils";
import type { WorkflowLogEntry } from "@/lib/workflows/types";

import { LogOutcome } from "./workflow-logs";

/** The lines one step's quick log wrote in a run: when, how it left, what it said. */
export function StepLogs({
  entries,
  labels,
}: {
  entries: WorkflowLogEntry[];
  /** The step's output ports' labels by id; an outcome without one reads as its id. */
  labels: Map<string, string>;
}) {
  const locale = useLocale();
  if (entries.length === 0) return null;
  return (
    <ul className="border-border mt-1 space-y-1 border-l-2 pl-2" data-testid="step-logs">
      {entries.map((entry) => (
        <li key={entry.id} className="text-xs">
          <span className="text-muted-foreground">
            {formatDateTimeSeconds(entry.created_at, locale)}
          </span>{" "}
          <LogOutcome entry={entry} label={labels.get(entry.outcome)} />
          <p className="break-words whitespace-pre-wrap">{entry.message}</p>
        </li>
      ))}
    </ul>
  );
}
