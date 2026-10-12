"use client";

import { CircleAlert, CircleCheck } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import { formatDate } from "@/lib/utils";
import type { McpCatalogEntry } from "@/types/mcp";

const DID_NOT_ANSWER = new Set(["unreachable", "broken", "refused"]);

/**
 * What the last catalog check found, on the card of the server it called (#2103).
 *
 * A server that answered says so, with the date and - where it listed them without
 * a credential - how many tools it has and how many only read. A curated server
 * that did not answer says that instead: it stays on the list, because somebody
 * chose it, but nobody should connect it believing it works. A server never
 * checked, or one with no address to call, says nothing.
 */
export function CatalogCheck({ entry }: { entry: McpCatalogEntry | null }) {
  const t = useTranslations("mcp");
  const locale = useLocale();
  if (!entry?.check) return null;
  const check = entry.check;
  const on = formatDate(check.checked_at, locale);
  // The action bar has room for "Checked 12 Oct" and not for the year; the
  // whole date, and the tool counts, are on hover.
  const short = new Date(check.checked_at).toLocaleDateString(locale, {
    month: "short",
    day: "numeric",
  });

  if (entry.verified) {
    // The date on the card; the tool counts, where the check got that far,
    // on hover - the action bar this sits in has room for one short phrase.
    const detail =
      check.tools === null
        ? t("checkedOn", { date: on })
        : t("checkedOnWithTools", {
            date: on,
            tools: check.tools,
            readOnly: check.read_only_tools ?? 0,
          });
    return (
      <span
        className="text-muted-foreground flex min-w-0 items-center gap-1 text-xs"
        title={detail}
      >
        <CircleCheck className="h-3.5 w-3.5 shrink-0 text-emerald-600 dark:text-emerald-500" />
        <span className="truncate">{t("checkedOn", { date: short })}</span>
      </span>
    );
  }
  if (!DID_NOT_ANSWER.has(check.outcome)) return null;
  return (
    <span
      className="text-destructive flex min-w-0 items-center gap-1 text-xs"
      title={t("didNotAnswerOn", { date: on })}
    >
      <CircleAlert className="h-3.5 w-3.5 shrink-0" />
      <span className="truncate">{t("noAnswerOn", { date: short })}</span>
    </span>
  );
}
