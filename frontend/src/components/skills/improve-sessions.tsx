"use client";

import Link from "next/link";
import { Sparkles } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import { usd } from "@/components/evals/format";
import { ErrorState } from "@/components/states";
import { Button, ListCard, Skeleton } from "@/components/ui";
import { getErrorMessage } from "@/lib/api-error";
import { ROUTES } from "@/lib/constants";
import { formatDateTime } from "@/lib/utils";
import type { SkillImprovement } from "@/types/skill-improvement";

const OPEN = new Set(["queued", "running", "waiting", "ready"]);

/** How a session ended, or that it is still open, as History names it. */
export function sessionResult(session: SkillImprovement): string {
  if (OPEN.has(session.status)) return "open";
  if (session.outcome === "applied" || session.outcome === "applied_pinned") return "applied";
  if (session.outcome !== null) return session.outcome;
  if (session.stop_reason === "expired") return "expired";
  if (session.status === "failed" || session.status === "cancelled") return session.status;
  return "stopped";
}

/** Where a session opens: the wizard, under the skill's page. */
export const sessionHref = (skillId: string, sessionId: string) =>
  `${ROUTES.SKILL_DETAIL(skillId)}/improve/${sessionId}`;

/**
 * The line's Improve sessions beside its versions: when and by whom each ran, how
 * it ended - applied as a version, a fork, discarded, expired - and what it cost.
 * An open one is continued from here; a finished one opens read-only.
 */
export function ImproveSessions({
  skillId,
  sessions,
  isLoading,
  error,
  more,
  loadingMore,
  onMore,
  versionLabel,
}: {
  skillId: string;
  sessions: SkillImprovement[];
  isLoading: boolean;
  error: unknown;
  /** Older sessions are left to read; how many is not known until they are. */
  more: boolean;
  loadingMore: boolean;
  onMore: () => void;
  /** The applied version's name, when History has it on its page. */
  versionLabel: (versionId: string) => string | null;
}) {
  const t = useTranslations("skills.page.history.sessions");
  const tErrors = useTranslations("errors");
  const locale = useLocale();
  return (
    <ListCard
      title={t("title")}
      counted={
        isLoading
          ? null
          : more
            ? t("countMore", { count: sessions.length })
            : t("count", { count: sessions.length })
      }
    >
      {error ? (
        <ErrorState description={getErrorMessage(error, tErrors)} />
      ) : isLoading ? (
        <Skeleton className="m-4 h-16" />
      ) : sessions.length === 0 ? (
        <p className="text-muted-foreground px-4 py-6 text-sm">{t("none")}</p>
      ) : (
        <ol className="divide-border divide-y">
          {sessions.map((session) => {
            const result = sessionResult(session);
            const applied =
              session.applied_version_id !== null ? versionLabel(session.applied_version_id) : null;
            return (
              <li
                key={session.id}
                className="flex flex-wrap items-center justify-between gap-2 px-4 py-3"
              >
                <div className="min-w-0 space-y-0.5">
                  <p className="flex items-center gap-1.5 text-sm">
                    <Sparkles className="text-muted-foreground size-3.5" aria-hidden />
                    {result === "applied" && applied !== null
                      ? t("appliedAs", { version: applied })
                      : t(`result.${result}`)}
                  </p>
                  <p className="text-muted-foreground text-xs">
                    {t("meta", {
                      who: session.created_by?.name ?? t("unknownStarter"),
                      when: formatDateTime(session.created_at, locale),
                      line: session.line_name,
                      cost: usd(session.spent_usd, locale),
                    })}
                  </p>
                </div>
                <Link
                  className="text-sm underline underline-offset-4"
                  href={sessionHref(skillId, session.id)}
                >
                  {result === "open" ? t("continue") : t("open")}
                </Link>
              </li>
            );
          })}
        </ol>
      )}
      {more && (
        <div className="px-4 pb-3">
          <Button variant="outline" size="sm" loading={loadingMore} onClick={onMore}>
            {t("more")}
          </Button>
        </div>
      )}
    </ListCard>
  );
}
