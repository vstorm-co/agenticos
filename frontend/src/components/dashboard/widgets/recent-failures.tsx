"use client";

import { useMemo } from "react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";

import { useAgents, useRecentFailures } from "@/hooks";
import { ROUTES } from "@/lib/constants";
import { timeAgo } from "@/lib/utils";
import { AgentFace } from "../agent-face";
import { WidgetFrame } from "../widget-frame";
import { TriangleAlert } from "lucide-react";

import { WidgetEmptyBody, WidgetErrorBody, WidgetSkeleton } from "../widget-states";
import type { DashboardWidgetProps } from "./types";

/** How many runs to ask for, against the five groups the card has room for. */
const FAILURE_CANDIDATES = 25;

/** How many grouped rows the card draws. */
const SHOWN_GROUPS = 5;

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
/**
 * A failure's first clause - what happened - without the advice after it. The
 * run's message reads "The run did not finish (RuntimeError) - retry it, and
 * check…"; one line of a card has room for the first half, and the whole
 * sentence is a hover away and on the run itself.
 */
function headline(message: string): string {
  const cut = message.indexOf(" - ");
  return cut > 0 ? message.slice(0, cut) : message;
}

export function RecentFailuresWidget({ title, hint, seeAll, options }: DashboardWidgetProps) {
  const t = useTranslations("dashboard.widgets.recent-failures");
  const tTime = useTranslations("time");
  const locale = useLocale();
  // Ask for more than the five rows this card draws, because the grouping
  // happens *here*: five runs that all failed the same way collapse to one
  // row, and if five is all that was fetched the four rows that frees stay
  // empty while four genuinely different failures sit unread on the next page.
  // Twenty-five is the run list's own page size, so this costs no extra round
  // trip shape - and what is drawn is still five groups.
  const { failures, isLoading, error, refetch } = useRecentFailures(FAILURE_CANDIDATES);
  const { agents } = useAgents();
  const names = new Map(agents.map((agent) => [agent.id, agent.name]));
  const groups = useMemo(
    () =>
      groupFailures(failures, (run) =>
        run.status === "budget_exceeded" ? t("budgetExceeded") : (run.error ?? t("failed")),
      ).slice(0, SHOWN_GROUPS),
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
              <AgentFace agentId={group.agentId} className="size-8" />
              <span className="min-w-0 flex-1">
                <span className="text-foreground block truncate font-medium">
                  {names.get(group.agentId) ?? t("unknownAgent")}
                </span>
                {/* How many times sits in the line that says what happened, as
                    words: a red pill beside the agent's name shouted an alarm
                    over a row the card already files under failures. */}
                <span
                  className="text-muted-foreground block truncate text-xs"
                  title={group.message}
                >
                  {headline(group.message)}
                  {group.count > 1 ? ` · ${t("timesFailed", { count: group.count })}` : ""}
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
