"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";

import { AgentAvatar } from "@/components/agents/agent-avatar";
import type { UsageDay, UsageLine } from "@/components/charts/usage-lines.impl";
import { ErrorState } from "@/components/states";
import { ListCard, Skeleton } from "@/components/ui";
import { useSkillUsage } from "@/hooks/use-skill-versions";
import { getErrorMessage } from "@/lib/api-error";
import { ROUTES } from "@/lib/constants";
import { CHART_MIN_HEIGHT, SERIES_TOKENS, seriesColor } from "@/lib/dashboard/system";
import { cn, formatDate } from "@/lib/utils";
import type { SkillAgentUsage, SkillUsage } from "@/types/skill-versions";

const UsageLinesImpl = dynamic(
  () => import("@/components/charts/usage-lines.impl").then((m) => m.UsageLinesImpl),
  {
    ssr: false,
    loading: () => <div className="bg-muted h-full w-full animate-pulse rounded-md" />,
  },
);

/** The window the page counts use over. */
const DAYS = 30;

const DASHES = [undefined, "6 3", "2 3"];

/**
 * Every day from `since` to `today`, each agent's loads on it, zero where it has
 * none; null when the server sent no days, which draws no chart.
 */
export function usageDays(
  usage: SkillUsage,
  label: (day: string) => string,
  today: Date = new Date(),
): { lines: UsageLine[]; days: UsageDay[] } | null {
  if (usage.agents.every((agent) => agent.daily === undefined)) return null;
  const lines = usage.agents.map((agent, index) => ({
    key: agent.agent_id,
    name: agent.agent_name,
    color: seriesColor(index),
    dash: DASHES[Math.floor(index / SERIES_TOKENS.length) % DASHES.length],
  }));
  const days: UsageDay[] = [];
  const end = today.toISOString().slice(0, 10);
  for (let at = new Date(usage.since.slice(0, 10)); ; at.setUTCDate(at.getUTCDate() + 1)) {
    const day = at.toISOString().slice(0, 10);
    const row: UsageDay = { day: label(day) };
    for (const agent of usage.agents) {
      row[agent.agent_id] = agent.daily?.find((point) => point.date === day)?.loads ?? 0;
    }
    days.push(row);
    if (day >= end) break;
  }
  return { lines, days };
}

/**
 * How often each agent used the skill in the last thirty days: a line per agent
 * by day, then each agent's runs that opened it and the files they read. Agents
 * the reader cannot see are a count. Eval and test-panel runs are left out, so
 * this is real use. Reading it needs `runs:view`, so the page draws it only for
 * such a reader.
 */
export function SkillUsageCard({
  skillId,
  agents,
}: {
  skillId: string;
  /** The skill's agents as the page read them, whose faces the table draws. */
  agents: SkillAgentUsage[];
}) {
  const t = useTranslations("skills.page.usage");
  const tErrors = useTranslations("errors");
  const locale = useLocale();
  const { usage, isLoading, error } = useSkillUsage(skillId, DAYS);
  const chart =
    usage &&
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
            <div
              className={cn("h-56 px-2 pt-4", CHART_MIN_HEIGHT)}
              role="img"
              aria-label={t("chart")}
            >
              <UsageLinesImpl lines={chart.lines} days={chart.days} />
            </div>
          )}
          <UsageTable usage={usage} agents={agents} />
        </>
      )}
    </ListCard>
  );
}

function UsageTable({ usage, agents }: { usage: SkillUsage; agents: SkillAgentUsage[] }) {
  const t = useTranslations("skills.page.usage");
  const locale = useLocale();
  const faces = new Map(agents.map((usage) => [usage.agent.id, usage.agent]));
  return (
    <table className="w-full text-sm">
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
                  slug={faces.get(agent.agent_id)?.slug ?? agent.agent_id}
                  hasAvatar={faces.get(agent.agent_id)?.has_avatar}
                  colorSlot={faces.get(agent.agent_id)?.avatar_color}
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
              {agent.last_loaded_at ? formatDate(agent.last_loaded_at, locale) : t("never")}
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
