"use client";

import { useFormatter, useTranslations } from "next-intl";
import { NativeDisclosure } from "@/components/ui/native-disclosure";
import { Progress } from "@/components/ui";
import type { SubscriptionUsage as Usage } from "@/lib/subscription-accounts-api";

/** Provider observations are dated snapshots, never a live billing estimate. */
export function SubscriptionUsage({ usage }: { usage?: Usage }) {
  const t = useTranslations("modelSources");
  const format = useFormatter();
  if (!usage || usage.status === "unavailable" || usage.windows.length === 0) return null;
  return (
    <NativeDisclosure open className="text-muted-foreground text-xs">
      <summary className="cursor-pointer py-1 font-medium">{t("usageAndLimits")}</summary>

      <div className="space-y-3 py-2">
        {usage.status === "stale" && <p>{t("usageStale")}</p>}
        {usage.windows.map((window) => (
          <div key={window.kind} className="space-y-1.5">
            <div className="flex items-center justify-between gap-3">
              <span>
                {window.duration_minutes === 300
                  ? t("fiveHourWindow")
                  : window.duration_minutes === 10080
                    ? t("weeklyWindow")
                    : window.duration_minutes
                      ? t("minutesWindow", { minutes: window.duration_minutes })
                      : t("usageWindow")}
              </span>
              <span className="text-foreground font-medium">
                {t("usageRemaining", {
                  remaining: format.number(window.remaining_percent / 100, {
                    style: "percent",
                    maximumFractionDigits: 1,
                  }),
                })}
              </span>
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
  );
}
