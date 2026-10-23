"use client";

import type { ReactNode } from "react";
import { useLocale, useTranslations } from "next-intl";

import { useUsageStats } from "@/hooks";
import { useWaitingOnMe } from "@/hooks/use-waiting-on-me";
import { useAuthStore } from "@/stores";
import type { Period } from "@/lib/dashboard/period";
import { PageHeader } from "./page-header";

/** What a greeting calls a person: the first word of their name, else their address's local part. */
export function firstName(
  fullName: string | null | undefined,
  email: string | undefined,
): string | null {
  const given = fullName?.trim().split(/\s+/)[0];
  if (given) return given;
  return email?.split("@")[0] || null;
}

/** Which greeting the hour asks for. */
export function partOfDay(hour: number): "morning" | "afternoon" | "evening" {
  if (hour < 12) return "morning";
  return hour < 18 ? "afternoon" : "evening";
}

/**
 * A person's own dashboard opens on them: the day, a greeting by name, what
 * happened in the period and everything waiting on them - their tool calls,
 * answers sent to review, failing suites and the assistant's suggestions.
 *
 * "Dashboard" and a description of the page told a person nothing they did not
 * know; this line is the answer they opened it for, before any card. It reads
 * the same queries the cards below do, so it costs no request of its own. The
 * date and greeting are the browser's, not the server's: a greeting rendered
 * for the host's time zone says "good morning" at a reader's midnight.
 */
export function MeHeader({
  period,
  canRun,
  actions,
}: {
  period: Period;
  /** Whether the reader runs agents at all - a viewer has no runs to sum up. */
  canRun: boolean;
  actions?: ReactNode;
}) {
  const t = useTranslations("dashboard.greeting");
  const tPage = useTranslations("dashboard");
  const locale = useLocale();
  const user = useAuthStore((state) => state.user);
  const { usage } = useUsageStats(
    { from: period.from, to: period.to },
    { scope: "own", enabled: canRun },
  );
  const now = new Date();
  const name = firstName(user?.full_name, user?.email);
  const runs = usage?.total_runs ?? 0;
  const others = useWaitingOnMe();
  const waiting = (
    [
      ["approvals", usage?.pending_approvals ?? 0],
      ["review", others.review],
      ["suites", others.suites],
      ["suggestions", others.suggestions],
    ] as const
  )
    .filter(([, count]) => count > 0)
    .map(([kind, count]) => t(`waiting.${kind}`, { count }));
  const bold = (chunks: ReactNode) => <span className="text-foreground font-medium">{chunks}</span>;

  return (
    <PageHeader
      title={
        <span className="flex flex-col">
          <span className="text-muted-foreground text-sm font-normal" suppressHydrationWarning>
            {new Intl.DateTimeFormat(locale, {
              weekday: "long",
              day: "numeric",
              month: "long",
            }).format(now)}
          </span>
          <span suppressHydrationWarning>
            {name === null
              ? t(partOfDay(now.getHours()))
              : t(`${partOfDay(now.getHours())}Named`, { name })}
          </span>
        </span>
      }
      description={
        usage ? (
          <>
            {t.rich("ran", { runs, b: bold })}{" "}
            {waiting.length === 0
              ? t("nothingWaiting")
              : t.rich("waitingOn", {
                  items: new Intl.ListFormat(locale, { type: "conjunction" }).format(waiting),
                  b: bold,
                })}
          </>
        ) : (
          tPage("views.me.description")
        )
      }
      actions={actions}
    />
  );
}
