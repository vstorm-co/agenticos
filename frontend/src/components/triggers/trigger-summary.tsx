"use client";

import { useTranslations } from "next-intl";

import { triggerSummary, WEEKDAYS } from "@/lib/trigger-format";
import type { Trigger } from "@/types/triggers";

/** The event phrase for a portal preset, as a fixed key under `triggers.event`. */
function presetEventKey(portalKey: string): string {
  switch (portalKey) {
    case "github":
      return "event.presetGithub";
    case "email":
      return "event.presetEmail";
    default:
      return "event.presetGeneric";
  }
}

/**
 * What makes a trigger fire, in one line - "Every 15 minutes", "Daily at 09:00
 * UTC", "At 09:00 UTC on Mon, Tue", "On new GitHub issues".
 *
 * The summary is reduced to a discriminated union first, so every branch here is
 * a fixed translation key and a count: an interval is an ICU plural per unit, so
 * "1 minute" and "15 minutes" are the message's job rather than English glued
 * together in the component. A cron the builder wrote reads in the same plain
 * language the builder showed; raw cron notation only appears for an expression
 * the user typed into Advanced themselves.
 */
export function TriggerSummary({ trigger }: { trigger: Trigger }) {
  const t = useTranslations("triggers");
  const summary = triggerSummary(trigger);

  switch (summary.kind) {
    case "interval":
      if (summary.unit === "days") return <>{t("cadence.everyDays", { count: summary.count })}</>;
      if (summary.unit === "hours") return <>{t("cadence.everyHours", { count: summary.count })}</>;
      return <>{t("cadence.everyMinutes", { count: summary.count })}</>;
    case "cron":
      return <>{t("cadence.cron", { expression: summary.expression })}</>;
    case "cronDaily":
      return <>{t("cadence.cronDaily", { time: summary.time })}</>;
    case "cronWeekly":
      // Monday-first, the order the picker shows, not cron's Sunday-zero order.
      return (
        <>
          {t("cadence.cronWeekly", {
            time: summary.time,
            days: WEEKDAYS.filter((day) => summary.weekdays.includes(day.value))
              .map((day) => t(day.key))
              .join(", "),
          })}
        </>
      );
    case "cronMonthly":
      return <>{t("cadence.cronMonthly", { day: summary.day, time: summary.time })}</>;
    case "preset":
      // One static ICU key, "{event} in {target}", with the event phrase chosen
      // per portal by a fixed key so the catalog check can see it.
      return (
        <>
          {t("event.presetSummary", {
            event: t(presetEventKey(summary.portalKey)),
            target: summary.target,
          })}
        </>
      );
    case "event":
      switch (summary.source) {
        case "github":
          return <>{t("event.github")}</>;
        case "email":
          return <>{t("event.email")}</>;
        case "webhook":
          return <>{t("event.webhook")}</>;
      }
  }
}
