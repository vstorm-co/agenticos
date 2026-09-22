"use client";

import { useMemo } from "react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";

import { useAgents, useRecentFailures } from "@/hooks";
import { ROUTES } from "@/lib/constants";
import { timeAgo } from "@/lib/utils";
import { WidgetFrame } from "../widget-frame";
import { TriangleAlert } from "lucide-react";

import { WidgetEmptyBody, WidgetErrorBody, WidgetSkeleton } from "../widget-states";
import type { DashboardWidgetProps } from "./types";

/** One agent failing the same way, however many times it did it. */
interface FailureGroup {
  key: string;
  agentId: string;
  /** What went wrong, as the run recorded it. */
  message: string;
  /** The newest run in the group - what "when" means for a group. */
  startedAt: string | null;
  count: number;
}

/**
 * Collapse runs that failed the same way on the same agent.
 *
 * The card asked for five runs and drew five rows, and a run that fails
 * usually fails repeatedly for one reason - so the ordinary case was the same
 * sentence five times, truncated at the same word, carrying one fact in the
 * whole card. Grouped, the same five runs are one row saying it happened five
 * times, and the four rows that frees go to failures that are genuinely
 * different.
 *
 * Grouped on the message itself rather than on a parsed exception name: the
 * text is the backend's prose and picking `(RuntimeError)` out of it is a
 * guess about a format nothing guarantees. Identical strings group; anything
 * else stays its own row, which is the safe direction to be wrong in.
 *
 * Insertion order is preserved, so the list stays newest-first - the caller
 * hands them over already sorted.
 */
function groupFailures(
  failures: {
    id: string;
    agent_id: string;
    status: string;
    error: string | null;
    started_at: string | null;
  }[],
  describe: (run: { status: string; error: string | null }) => string,
): FailureGroup[] {
  const groups = new Map<string, FailureGroup>();
  for (const run of failures) {
    const message = describe(run);
    const key = `${run.agent_id}\u0000${message}`;
    const seen = groups.get(key);
    if (seen) {
      seen.count += 1;
      continue;
    }
    groups.set(key, {
      key,
      agentId: run.agent_id,
      message,
      startedAt: run.started_at,
      count: 1,
    });
  }
  return [...groups.values()];
}

/**
 * Failed and out-of-budget runs, newest first - the two statuses that mean
 * something needs a look, asked of /runs as a list because that is the
 * operator's actual question.
 */
export function RecentFailuresWidget({ title, hint, seeAll, options }: DashboardWidgetProps) {
  const t = useTranslations("dashboard.widgets.recent-failures");
  const tTime = useTranslations("time");
  const locale = useLocale();
  const { failures, isLoading, error, refetch } = useRecentFailures(5);
  const { agents } = useAgents();
  const names = new Map(agents.map((agent) => [agent.id, agent.name]));
  const groups = useMemo(
    () =>
      groupFailures(failures, (run) =>
        run.status === "budget_exceeded" ? t("budgetExceeded") : (run.error ?? t("failed")),
      ),
    [failures, t],
  );

  return (
    <WidgetFrame title={title} hint={hint} seeAll={seeAll} options={options}>
      {isLoading ? (
        <WidgetSkeleton />
      ) : error ? (
        <WidgetErrorBody onRetry={() => refetch()} />
      ) : failures.length === 0 ? (
        <WidgetEmptyBody
          icon={TriangleAlert}
          title={t("empty.title")}
          description={t("empty.description")}
        />
      ) : (
        <ul className="space-y-2">
          {groups.map((group) => (
            <li key={group.key} className="flex items-center gap-3 text-sm">
              <span className="min-w-0 flex-1">
                <span className="flex min-w-0 items-center gap-1.5">
                  <span className="text-foreground truncate">
                    {names.get(group.agentId) ?? t("unknownAgent")}
                  </span>
                  {/* The count is the whole point of grouping, so it is on the
                      agent's line rather than buried in the message beneath. */}
                  {group.count > 1 ? (
                    <span className="border-destructive/35 bg-destructive/10 text-foreground shrink-0 rounded-full border px-1.5 py-px font-mono text-[10px] tabular-nums">
                      {t("timesFailed", { count: group.count })}
                    </span>
                  ) : null}
                </span>
                <span className="text-muted-foreground block truncate text-xs">
                  {group.message}
                  {group.startedAt ? ` · ${timeAgo(group.startedAt, tTime, locale)}` : ""}
                </span>
              </span>
              <Link
                href={ROUTES.RUNS}
                className="text-muted-foreground hover:text-foreground shrink-0 text-xs"
              >
                {t("open")}
              </Link>
            </li>
          ))}
        </ul>
      )}
    </WidgetFrame>
  );
}
