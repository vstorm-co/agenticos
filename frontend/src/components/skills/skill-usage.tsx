"use client";

import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";

import { AgentAvatar } from "@/components/agents/agent-avatar";
import type { UsageDay, UsageLine } from "@/components/charts/usage-lines.impl";
import { ErrorState } from "@/components/states";
import { ListCard, Skeleton } from "@/components/ui";
import { useSkillUsage } from "@/hooks/use-skill-versions";
import { getErrorMessage } from "@/lib/api-error";
import { ROUTES } from "@/lib/constants";
import { SERIES_TOKENS, seriesColor } from "@/lib/dashboard/system";
import { formatDate } from "@/lib/utils";
import type { SkillUsage, SkillUsageAgent } from "@/types/skill-versions";
import { UsageChart, type Face } from "./usage-chart";

/** The window the page counts use over. */
const DAYS = 30;

const DASHES = [undefined, "6 3", "2 3"];

/**
 * Each agent's loads by day, keyed under the agent: one row per day the server
 * counted, read off the first agent, since every agent carries the same days.
 */
export function usageDays(
  usage: SkillUsage,
  label: (day: string) => string,
): { lines: UsageLine[]; days: UsageDay[] } {
  const lines = usage.agents.map((agent, index) => ({
    key: agent.agent_id,
    name: agent.agent_name,
    color: seriesColor(index),
    dash: DASHES[Math.floor(index / SERIES_TOKENS.length) % DASHES.length],
  }));
  const dates = usage.agents[0]!.daily.map((point) => point.date);
  const days = dates.map((date) => {
    const row: UsageDay = { day: label(date) };
    for (const agent of usage.agents) {
      row[agent.agent_id] = agent.daily.find((point) => point.date === date)?.loads ?? 0;
    }
    return row;
  });
  return { lines, days };
}

/**
 * How often each agent used the skill in the last thirty days: one chart by day
 * overlaying the agents picked, then each agent's runs that opened it and the
 * files they read. Agents
 * the reader cannot see are a count. Eval and test-panel runs are left out, so
 * this is real use. Reading it needs `runs:view`, so the page draws it only for
 * such a reader.
 */
export function SkillUsageCard({ skillId }: { skillId: string }) {
  const t = useTranslations("skills.page.usage");
  const tErrors = useTranslations("errors");
  const locale = useLocale();
  const { usage, isLoading, error } = useSkillUsage(skillId, DAYS);
  const faceOf = (agent: SkillUsageAgent): Face => ({
    slug: agent.slug,
    hasAvatar: agent.has_avatar,
    colorSlot: agent.avatar_color,
  });
  const chart =
    usage &&
    usage.agents.length > 0 &&
    usageDays(usage, (day) =>
      new Date(day).toLocaleDateString(locale, { month: "short", day: "numeric", timeZone: "UTC" }),
    );
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
        <>
          {chart && (
            <UsageChart
              agents={usage.agents}
              lines={chart.lines}
              days={chart.days}
              faceOf={faceOf}
            />
          )}
          <UsageTable usage={usage} faceOf={faceOf} />
        </>
      )}
    </ListCard>
  );
}

function UsageTable({
  usage,
  faceOf,
}: {
  usage: SkillUsage;
  faceOf: (agent: SkillUsageAgent) => Face;
}) {
  const t = useTranslations("skills.page.usage");
  const locale = useLocale();
  return (
    <table className="w-full text-sm" aria-label={t("table.label")}>
      <thead className="text-muted-foreground text-left text-xs">
        <tr className="border-b">
          <th className="px-4 py-2 font-medium">{t("table.agent")}</th>
          <th className="px-4 py-2 text-right font-medium">{t("table.loads")}</th>
          <th className="px-4 py-2 text-right font-medium">{t("table.files")}</th>
          <th className="px-4 py-2 text-right font-medium">{t("table.last")}</th>
        </tr>
      </thead>
      <tbody className="divide-border divide-y">
        {usage.agents.map((agent) => (
          <tr key={agent.agent_id}>
            <td className="px-4 py-2">
              <div className="flex min-w-0 items-center gap-2">
                <AgentAvatar
                  agentId={agent.agent_id}
                  slug={faceOf(agent).slug}
                  hasAvatar={faceOf(agent).hasAvatar}
                  colorSlot={faceOf(agent).colorSlot}
                  size="sm"
                />
                <Link
                  href={ROUTES.AGENT_DETAIL(agent.agent_id)}
                  className="min-w-0 truncate font-medium hover:underline"
                >
                  {agent.agent_name}
                </Link>
              </div>
            </td>
            <td className="px-4 py-2 text-right tabular-nums">{agent.loads}</td>
            <td className="px-4 py-2 text-right tabular-nums">{agent.resource_reads}</td>
            <td className="text-muted-foreground px-4 py-2 text-right text-xs">
              {agent.last_loaded_at
                ? formatDate(agent.last_loaded_at, locale)
                : agent.workspace_reads > 0
                  ? t("probable", { count: agent.workspace_reads })
                  : t("never")}
            </td>
          </tr>
        ))}
        {usage.hidden_agents > 0 && (
          <tr>
            <td colSpan={4} className="text-muted-foreground px-4 py-2 text-xs">
              {t("hidden", { count: usage.hidden_agents, loads: usage.hidden_loads })}
            </td>
          </tr>
        )}
      </tbody>
    </table>
  );
}
