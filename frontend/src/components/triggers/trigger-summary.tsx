"use client";

import { useTranslations } from "next-intl";

import { triggerSummary } from "@/lib/trigger-format";
import type { Trigger } from "@/types/triggers";

/**
 * What makes a trigger fire, in one line - "Every 15 minutes", "Daily at 09:00
 * UTC" via its cron, "On new GitHub issues".
 *
 * The summary is reduced to a discriminated union first, so every branch here is
 * a fixed translation key and a count: an interval is an ICU plural per unit, so
 * "1 minute" and "15 minutes" are the message's job rather than English glued
 * together in the component.
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
    case "event":
      switch (summary.source) {
        case "github":
          return <>{t("event.github")}</>;
        case "email":
          return <>{t("event.email")}</>;
        case "linkedin":
          return <>{t("event.linkedin")}</>;
        case "webhook":
          return <>{t("event.webhook")}</>;
      }
  }
}
