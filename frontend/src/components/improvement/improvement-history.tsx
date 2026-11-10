"use client";

import Link from "next/link";
import { History } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import { usd } from "@/components/evals/format";
import { ErrorState, LoadingState } from "@/components/states";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui";
import { useImprovements } from "@/hooks/use-improvements";
import { getErrorMessage } from "@/lib/api-error";
import { isActive } from "@/lib/improvement-steps";
import type { Improvement } from "@/types/improvement";

/** How the session's chosen round - or its last - measured, in the wizard's own words. */
function useResult(): (session: Improvement) => string {
  const t = useTranslations("improvement");
  return (session) => {
    if (isActive(session))
      return t("history.attemptUnderWay", {
        number: session.iteration,
        max: session.max_iterations,
      });
    const round =
      session.iterations.find((item) => item.id === session.best_iteration_id) ??
      session.iterations.at(-1);
    const fixed = round?.verdict_detail?.fixed;
    const broken = round?.verdict_detail?.broken;
    if (!round?.verdict) return t("history.notMeasured");
    return t(`verdict.${round.verdict}`, {
      fixed: Number(fixed ?? 0),
      broken: Number(broken ?? 0),
    });
  };
}

function Row({ session }: { session: Improvement }) {
  const t = useTranslations("improvement");
  const locale = useLocale();
  const result = useResult();
  const starter = session.timeline.find((event) => event.action === "improvement.started");
  const decision =
    session.status === "published" && session.published_version != null
      ? t("history.publishedVersion", { version: session.published_version })
      : t(`status.${session.status}`);
  return (
    <li>
      <Link
        href={`/agents/${session.agent_id}/improve/${session.id}`}
        className="hover:bg-muted/50 block space-y-1 rounded-lg px-3 py-2"
      >
        <span className="flex flex-wrap items-baseline justify-between gap-x-3 gap-y-1">
          <span className="text-sm font-medium">{decision}</span>
          <span className="text-muted-foreground text-xs tabular-nums">
            {new Date(session.created_at).toLocaleDateString(locale)}
          </span>
        </span>
        <span className="block text-sm">{result(session)}</span>
        {session.stop_reason && (
          <span className="text-muted-foreground block text-xs">
            {t(`stop.${session.stop_reason}`)}
          </span>
        )}
        <span className="text-muted-foreground block text-xs">
          {starter?.actor_name
            ? t("history.startedBy", {
                name: starter.actor_name,
                cost: usd(session.spent_usd, locale),
              })
            : t("history.cost", { cost: usd(session.spent_usd, locale) })}
        </span>
      </Link>
    </li>
  );
}

/**
 * The agent's improvement sessions, newest first: when each ran, who started it,
 * how it measured, what was decided and what it cost. Each opens its wizard,
 * which a finished session shows only to be read.
 */
export function ImprovementHistory({ agentId }: { agentId: string }) {
  const t = useTranslations("improvement.history");
  const tErrors = useTranslations("errors");
  const { sessions, isLoading, error } = useImprovements(agentId);
  return (
    <Card data-tour="agent-improvement-history">
      <CardHeader>
        <CardTitle className="flex items-center gap-2">
          <History className="h-4 w-4" aria-hidden />
          {t("title")}
        </CardTitle>
        <CardDescription>{t("description")}</CardDescription>
      </CardHeader>
      <CardContent>
        {isLoading ? (
          <LoadingState variant="skeleton-list" rows={2} />
        ) : error ? (
          <ErrorState description={getErrorMessage(error, tErrors)} />
        ) : sessions.length === 0 ? (
          <p className="text-muted-foreground text-sm">{t("empty")}</p>
        ) : (
          <ul className="divide-border -mx-3 divide-y">
            {sessions.map((session) => (
              <Row key={session.id} session={session} />
            ))}
          </ul>
        )}
      </CardContent>
    </Card>
  );
}
