"use client";

import type { ReactNode } from "react";
import { useLocale, useTranslations } from "next-intl";

import { useUsageStats } from "@/hooks";
import { useLocalClock } from "@/hooks/use-local-clock";
import { useWaitingOnMe, waitingOn } from "@/hooks/use-waiting-on-me";
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
export function partOfDay(hour: number): "night" | "morning" | "afternoon" | "evening" {
  if (hour < 6) return "night";
  if (hour < 12) return "morning";
  return hour < 18 ? "afternoon" : "evening";
}

/** One stable greeting and action layout for every dashboard scope. */
export function DashboardHeader({
  description,
  actions,
}: {
  description: ReactNode;
  actions?: ReactNode;
}) {
  const t = useTranslations("dashboard.greeting");
  const locale = useLocale();
  const user = useAuthStore((state) => state.user);
  const now = useLocalClock();
  const greeting = now === null ? "night" : partOfDay(now.getHours());
  const name = firstName(user?.full_name, user?.email);
  return (
    <PageHeader
      className="mb-4 [&>div>p]:line-clamp-2 [&>div>p]:min-h-[2lh]"
      descriptionMode="summary"
      title={
        <span className="flex flex-col">
          <span className="text-muted-foreground text-sm font-normal">
            {now &&
              new Intl.DateTimeFormat(locale, {
                weekday: "long",
                day: "numeric",
                month: "long",
              }).format(now)}
          </span>
          <span>{name === null ? t(greeting) : t(`${greeting}Named`, { name })}</span>
        </span>
      }
      description={description}
      actions={actions}
    />
  );
}

/** Personal activity stays scoped to its reader; other views need no personal queries. */
export function MeHeader({
  period,
  canRun,
  actions,
}: {
  period: Period;
  canRun: boolean;
  actions?: ReactNode;
}) {
  const t = useTranslations("dashboard.greeting");
  const tPage = useTranslations("dashboard");
  const locale = useLocale();
  const { usage } = useUsageStats(
    { from: period.from, to: period.to },
    { scope: "own", enabled: canRun },
  );
  const runs = usage?.total_runs ?? 0;
  const others = useWaitingOnMe();
  const waiting = waitingOn(usage?.pending_approvals ?? 0, others).map(([kind, count]) =>
    t(`waiting.${kind}`, { count }),
  );
  const bold = (chunks: ReactNode) => <span className="text-foreground font-medium">{chunks}</span>;
  return (
    <DashboardHeader
      description={
        usage ? (
          <>
            {t.rich("ran", { runs, b: bold })}{" "}
            {waiting.length > 0
              ? t.rich("waitingOn", {
                  items: new Intl.ListFormat(locale, { type: "conjunction" }).format(waiting),
                  b: bold,
                })
              : others.settled && t("nothingWaiting")}
          </>
        ) : (
          tPage("views.me.description")
        )
      }
      actions={actions}
    />
  );
}
