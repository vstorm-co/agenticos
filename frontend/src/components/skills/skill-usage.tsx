"use client";

import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";

import { ErrorState } from "@/components/states";
import { ListCard, Skeleton } from "@/components/ui";
import { useSkillUsage } from "@/hooks/use-skill-versions";
import { getErrorMessage } from "@/lib/api-error";
import { ROUTES } from "@/lib/constants";
import { formatDate } from "@/lib/utils";

/** The window the page counts use over. */
const DAYS = 30;

/**
 * How often each agent used the skill in the last thirty days: the runs that
 * opened it, and the files they read from it. Agents the reader cannot see are a
 * count. Eval and test-panel runs are left out, so this is real use. Reading it
 * needs `runs:view`, so the page draws it only for such a reader.
 */
export function SkillUsageCard({ skillId }: { skillId: string }) {
  const t = useTranslations("skills.page.usage");
  const tErrors = useTranslations("errors");
  const locale = useLocale();
  const { usage, isLoading, error } = useSkillUsage(skillId, DAYS);
  return (
    <ListCard
      title={t("title", { days: DAYS })}
      counted={usage ? t("loads", { count: usage.loads + usage.hidden_loads }) : null}
      headerTour="skill-usage"
    >
      {error ? (
        <ErrorState description={getErrorMessage(error, tErrors)} />
      ) : isLoading || !usage ? (
        <Skeleton className="m-4 h-16" />
      ) : usage.agents.length + usage.hidden_agents === 0 ? (
        <p className="text-muted-foreground p-4 text-sm">{t("none", { days: DAYS })}</p>
      ) : (
        <ul className="divide-border divide-y text-sm">
          {usage.agents.map((agent) => (
            <li
              key={agent.agent_id}
              className="flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-2"
            >
              <Link
                href={ROUTES.AGENT_DETAIL(agent.agent_id)}
                className="min-w-0 truncate font-medium hover:underline"
              >
                {agent.agent_name}
              </Link>
              <span className="text-muted-foreground text-xs">
                {t("agent", {
                  loads: agent.loads,
                  files: agent.resource_reads,
                  last: agent.last_loaded_at ? formatDate(agent.last_loaded_at, locale) : "",
                  seen: agent.last_loaded_at ? "yes" : "no",
                })}
              </span>
            </li>
          ))}
          {usage.hidden_agents > 0 && (
            <li className="text-muted-foreground px-4 py-2 text-xs">
              {t("hidden", { count: usage.hidden_agents, loads: usage.hidden_loads })}
            </li>
          )}
        </ul>
      )}
    </ListCard>
  );
}
