"use client";

import type { ReactNode } from "react";
import { useLocale, useTranslations } from "next-intl";

import { useUsageStats } from "@/hooks";
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
 * A person's own dashboard opens on them: the day, a greeting by name, and one
 * sentence of what happened in the period and what is waiting on them.
 *
 * "Dashboard" and a description of the page told a person nothing they did not
 * know; this line is the answer they opened it for, before any card. It reads
 * the same own-scope usage the cards below do, so it costs no request of its
 * own. The date and greeting are the browser's, not the server's: a greeting
 * rendered for the host's time zone says "good morning" at a reader's midnight.
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
  const waiting = usage?.pending_approvals ?? 0;

  return (
    <PageHeader
      descriptionMode="summary"
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
        usage
          ? t.rich("summary", {
              runs,
              waiting,
              b: (chunks) => <span className="text-foreground font-medium">{chunks}</span>,
            })
          : tPage("views.me.description")
      }
      actions={actions}
    />
  );
}
