"use client";

import Link from "next/link";
import { Activity, ArrowRight } from "lucide-react";

import { RunStatusBadge } from "@/components/agents/status-badge";
import { ROUTES } from "@/lib/constants";
import { formatDate } from "@/lib/utils";
import type { AgentRun } from "@/types/runs";

interface RunSummaryProps {
  agentId: string;
  runs: AgentRun[];
}

/** The three numbers worth putting above a run list, derived once. */
interface Tally {
  total: number;
  failed: number;
  /**
   * Summed as a float, and only here.
   *
   * `cost_usd` is a serialised Decimal and the rule elsewhere is not to parse it
   * for arithmetic - the ledger, budget enforcement and anything an invoice is
   * checked against all stay in Decimal server-side. This is a headline on a
   * builder panel, rounded to cents, next to a link to the page that computes it
   * properly. Being a fraction of a cent out here costs nothing; doing it in a
   * budget check would.
   */
  spent: number;
  /** True when any run in the window priced a model it had no price for. */
  partial: boolean;
}

function tally(runs: AgentRun[]): Tally {
  return {
    total: runs.length,
    failed: runs.filter((run) => run.status === "failed").length,
    spent: runs.reduce((sum, run) => sum + Number(run.cost_usd), 0),
    partial: runs.some((run) => run.cost_is_partial),
  };
}

/**
 * How this agent has actually been behaving, above a link to the page that owns
 * the detail.
 *
 * This was ten rows of status, model and cost, in that order and nothing else -
 * a table with no headers, no times, and no answer to the question somebody
 * opens it for, which is "is this agent working?". Ten identical-looking rows do
 * not answer it; "9 runs, 1 failed" does, and it does it before anything is
 * read.
 *
 * The detail is deliberately not rebuilt here. Activity already has the run
 * table with surfaces, tokens, versions and spend breakdowns, and a second
 * partial copy of it in the Builder is one that drifts. So this panel answers
 * the summary question and hands over.
 */
export function RunSummary({ agentId, runs }: RunSummaryProps) {
  const stats = tally(runs);
  const activityHref = `${ROUTES.RUNS}?agent=${agentId}`;

  if (stats.total === 0) {
    return (
      <div className="border-border rounded-lg border border-dashed p-6 text-center">
        <Activity className="text-muted-foreground mx-auto h-5 w-5" />
        <p className="text-muted-foreground mt-2 text-sm">
          This agent has not run yet. Publish it and send it a message, or test it from the header.
        </p>
      </div>
    );
  }

  return (
    <div className="space-y-3">
      <div className="grid gap-2 sm:grid-cols-3">
        <Figure label="Runs" value={String(stats.total)} />
        <Figure
          label="Failed"
          value={String(stats.failed)}
          // Only when there are any. A red zero is an alarm about nothing, and a
          // panel that always looks slightly alarmed is one nobody reads.
          tone={stats.failed > 0 ? "bad" : "plain"}
        />
        <Figure
          label="Spent"
          value={`$${stats.spent.toFixed(2)}${stats.partial ? "+" : ""}`}
          hint={
            stats.partial ? "A model in these runs had no price, so this is a floor." : undefined
          }
        />
      </div>

      <ul className="divide-border divide-y rounded-md border">
        {/* Five, not ten. This is the "what just happened" glance; the page
            behind the link is where somebody goes to read a history. */}
        {runs.slice(0, 5).map((run) => (
          <li key={run.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 p-3 text-sm">
            <RunStatusBadge status={run.status} />
            <span className="text-muted-foreground text-xs">
              {run.started_at ? formatDate(run.started_at) : "not started"}
            </span>
            <span className="text-muted-foreground text-xs">{run.surface}</span>
            <span className="ml-auto font-mono text-xs">{run.model_label ?? "-"}</span>
            <span className="font-mono text-xs">${Number(run.cost_usd).toFixed(4)}</span>
          </li>
        ))}
      </ul>

      <Link
        href={activityHref}
        className="inline-flex items-center gap-1.5 text-sm underline underline-offset-4"
      >
        See every run in Activity
        <ArrowRight className="h-3.5 w-3.5" />
      </Link>
    </div>
  );
}

function Figure({
  label,
  value,
  tone = "plain",
  hint,
}: {
  label: string;
  value: string;
  tone?: "plain" | "bad";
  hint?: string;
}) {
  return (
    <div className="border-border rounded-lg border p-3">
      <p className="text-muted-foreground text-[11px] tracking-wide uppercase">{label}</p>
      <p className={tone === "bad" ? "text-destructive font-mono text-xl" : "font-mono text-xl"}>
        {value}
      </p>
      {hint && <p className="text-muted-foreground mt-0.5 text-xs">{hint}</p>}
    </div>
  );
}
