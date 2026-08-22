"use client";

import { useTranslations } from "next-intl";

import { cadenceText } from "@/lib/trigger-format";
import type { Trigger } from "@/types/triggers";

/**
 * What makes a trigger fire, in one line - "Every 15 minutes", "Daily at 09:00
 * UTC", "At 09:00 UTC on Mon, Tue", "On new GitHub issues".
 *
 * The sentence itself is `cadenceText`, because the dashboard's routines card
 * needs the same words as a string rather than as markup - a subtitle beside a
 * cost, where an element cannot go.
 */
export function TriggerSummary({ trigger }: { trigger: Trigger }) {
  const t = useTranslations("triggers");

  return <>{cadenceText(trigger, t)}</>;
}
