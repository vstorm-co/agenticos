"use client";

import { useLocale, useTranslations } from "next-intl";

import type { ReturnRefusal, ReturnedToMain } from "@/types/skill-merge";

/** Every refusal the console words itself. A code added to the type fails to compile here. */
const REFUSALS: Record<ReturnRefusal, true> = {
  agent_not_found: true,
  workflow_agent: true,
  architect_admin_only: true,
  system_agent_admin_only: true,
  via_specialist: true,
  not_bound: true,
  binding_problems: true,
  system_agent_parts: true,
  does_not_publish: true,
};

/**
 * What returning a fork's agents to main did. It can succeed in part: an agent the
 * reader may not change, one that reads the fork through a specialist, or one whose
 * new version waits in its draft stays on the fork, and the fork is archived only once
 * nobody reads it.
 */
export function ReturnedSummary({ returned }: { returned: ReturnedToMain }) {
  const t = useTranslations("skillImprovement.returned");
  const locale = useLocale();
  const list = new Intl.ListFormat(locale, { type: "conjunction" });
  const moved = returned.agents.filter((row) => row.refused === null);
  const live = moved.filter((row) => row.published);
  const drafts = moved.filter((row) => !row.published);
  const refused = returned.agents.flatMap((row) =>
    row.refused === null
      ? []
      : [
          {
            id: row.agent.id,
            name: row.agent.name,
            reason:
              row.refused_code && Object.hasOwn(REFUSALS, row.refused_code)
                ? t(`refusal.${row.refused_code}`)
                : row.refused,
          },
        ],
  );
  return (
    <section
      role="status"
      aria-label={t("title")}
      className="space-y-1.5 rounded-lg border p-3 text-sm"
    >
      {live.length > 0 && (
        <p>
          {t("live", { count: live.length, names: list.format(live.map((row) => row.agent.name)) })}
        </p>
      )}
      {drafts.length > 0 && (
        <p>
          {t("drafts", {
            count: drafts.length,
            names: list.format(drafts.map((row) => row.agent.name)),
          })}
        </p>
      )}
      {refused.length > 0 && (
        <ul className="text-warning space-y-1">
          {refused.map((row) => (
            <li key={row.id}>{t("refused", { name: row.name, reason: row.reason })}</li>
          ))}
        </ul>
      )}
      {returned.hidden > 0 && (
        <p className="text-muted-foreground text-xs">{t("hidden", { count: returned.hidden })}</p>
      )}
      <p>{returned.archived ? t("archived") : t("remaining", { count: returned.remaining })}</p>
    </section>
  );
}
