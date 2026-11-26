"use client";

import { useFormatter, useTranslations } from "next-intl";
import { NativeDisclosure } from "@/components/ui/native-disclosure";
import { Progress } from "@/components/ui";
import type { SubscriptionUsage as Usage } from "@/lib/subscription-accounts-api";

/** Provider observations are dated snapshots, never a live billing estimate. */
export function SubscriptionUsage({
  usage,
  compact = false,
}: {
  usage?: Usage;
  compact?: boolean;
}) {
  const t = useTranslations("modelSources");
  const format = useFormatter();
  const common = useTranslations("common");
  const windowLabel = (window: Usage["windows"][number]) =>
    window.label ??
    (window.duration_minutes === 300
      ? t("fiveHourWindow")
      : window.duration_minutes === 10080
        ? t("weeklyWindow")
        : window.duration_minutes === 1440
          ? t("dailyWindow")
          : window.duration_minutes && window.duration_minutes % 60 === 0
            ? t("hoursWindow", { hours: window.duration_minutes / 60 })
            : window.duration_minutes
              ? t("minutesWindow", { minutes: window.duration_minutes })
              : t("usageWindow"));
  const remaining = (window: Usage["windows"][number]) =>
    t("usageRemaining", {
      remaining: format.number(window.remaining_percent / 100, {
        style: "percent",
        maximumFractionDigits: 1,
      }),
    });
  if (!usage || usage.status === "unavailable" || usage.windows.length === 0) return null;
  return (
    <div className="text-muted-foreground min-w-0 text-xs">
      {compact && (
        <div className="grid grid-cols-[repeat(auto-fit,minmax(9rem,1fr))] gap-x-4 gap-y-2">
          {usage.windows.slice(0, 2).map((window, index) => (
            <div key={`${window.kind}:${index}`} className="min-w-0 space-y-1">
              <div className="flex items-baseline justify-between gap-2">
                <span className="truncate" title={windowLabel(window)}>
                  {windowLabel(window)}
                </span>
                <span className="text-foreground shrink-0 font-medium">{remaining(window)}</span>
              </div>
              <Progress
                className="h-1"
                value={window.remaining_percent}
                aria-label={windowLabel(window)}
                aria-valuetext={remaining(window)}
              />
            </div>
          ))}
        </div>
      )}
      {compact && usage.status === "stale" && <p className="mt-1">{t("usageStale")}</p>}
      <NativeDisclosure open={compact ? undefined : true} className={compact ? "mt-1" : undefined}>
        <summary className="cursor-pointer py-1 font-medium">
          {compact ? common("details") : t("usageAndLimits")}
        </summary>

        <div className="space-y-3 py-2">
          {!compact && usage.status === "stale" && <p>{t("usageStale")}</p>}
          {usage.windows.map((window, index) => (
            <div key={`${window.kind}:${index}`} className="space-y-1.5">
              <div className="flex items-center justify-between gap-3">
                <span>{windowLabel(window)}</span>
                <span className="text-foreground font-medium">{remaining(window)}</span>
              </div>
              <Progress value={100 - window.remaining_percent} aria-label={t("usageConsumed")} />
              {window.resets_at && (
                <p>
                  {t("usageResets", {
                    time: format.dateTime(new Date(window.resets_at), {
                      dateStyle: "short",
                      timeStyle: "short",
                    }),
                  })}
                </p>
              )}
            </div>
          ))}
          {usage.observed_at && (
            <p>
              {t("usageObserved", {
                time: format.dateTime(new Date(usage.observed_at), {
                  dateStyle: "short",
                  timeStyle: "short",
                }),
              })}
            </p>
          )}
        </div>
      </NativeDisclosure>
    </div>
  );
}
