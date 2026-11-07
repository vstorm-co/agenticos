"use client";

import { useLocale, useTranslations } from "next-intl";

import type { ReachedAgent } from "@/types/authoring";

/**
 * What applying a change to a context file or skill does, exactly: which agents
 * it goes live for and where, which eval suites it queues, and which guards check
 * it only at the next promotion - named for a reader of runs, counted for anybody
 * else - and how many more agents the reader may not see.
 */
export function GoesLive({ reaches, hidden }: { reaches: ReachedAgent[]; hidden: number }) {
  const t = useTranslations("authoring.goesLive");
  const locale = useLocale();
  const list = new Intl.ListFormat(locale, { type: "conjunction" });
  const agents = reaches.map((agent) =>
    t("agent", { name: agent.name, environments: list.format(agent.environments) }),
  );
  if (hidden > 0) agents.push(t("hidden", { count: hidden }));
  if (agents.length === 0) return <p className="text-muted-foreground text-xs">{t("nowhere")}</p>;
  const suites = (named: string[], count: number) =>
    named.length === count ? list.format(named) : t("suites", { count });
  const runsNow = reaches.flatMap((agent) => agent.runs_now);
  const runsNowCount = reaches.reduce((sum, agent) => sum + agent.runs_now_count, 0);
  const atPromotion = reaches.flatMap((agent) => agent.at_promotion);
  const atPromotionCount = reaches.reduce((sum, agent) => sum + agent.at_promotion_count, 0);
  return (
    <div className="space-y-0.5 text-xs text-amber-700 dark:text-amber-400">
      <p>{t("now", { agents: list.format(agents) })}</p>
      {runsNowCount > 0 && <p>{t("runsNow", { suites: suites(runsNow, runsNowCount) })}</p>}
      {atPromotionCount > 0 && (
        <p>
          {t("atPromotion", {
            suites: suites(atPromotion, atPromotionCount),
            count: atPromotionCount,
            named: atPromotion.length === atPromotionCount ? "yes" : "no",
          })}
        </p>
      )}
    </div>
  );
}
