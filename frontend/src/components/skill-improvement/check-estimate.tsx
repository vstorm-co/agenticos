"use client";

import { useLocale, useTranslations } from "next-intl";

import type { ContinuationEstimate } from "@/types/improvement";
import type { SkillContinuationEstimate } from "@/types/skill-improvement";

/**
 * Under a check's price: the agents it runs on, and the ones it cannot - each named,
 * with the reason - before anything is spent on them.
 */
export function CheckEstimate({ quote }: { quote: ContinuationEstimate }) {
  const t = useTranslations("skillImprovement.checkEstimate");
  const locale = useLocale();
  const check = (quote as SkillContinuationEstimate).check_estimate;
  if (!check) return null;
  const runs = check.agents.filter((row) => row.state !== "unknown");
  const unchecked = check.agents.filter((row) => row.state === "unknown");
  return (
    <div className="space-y-1.5 text-sm">
      <p>
        {t("agents", {
          count: runs.length,
          names: new Intl.ListFormat(locale, { type: "conjunction" }).format(
            runs.map((row) => row.agent.name),
          ),
        })}
      </p>
      {unchecked.length > 0 && (
        <ul className="text-warning space-y-1">
          {unchecked.map((row) => (
            <li key={`${row.agent.id}:${row.via_specialist ?? ""}`}>
              {t("unchecked", { name: row.agent.name, reason: row.unknown_reason ?? "failed" })}
            </li>
          ))}
        </ul>
      )}
      {check.hidden > 0 && (
        <p className="text-muted-foreground text-xs">{t("hidden", { count: check.hidden })}</p>
      )}
      {check.description_changed && (
        <p className="text-muted-foreground text-xs">{t("thorough")}</p>
      )}
    </div>
  );
}
