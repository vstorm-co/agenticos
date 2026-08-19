"use client";

import { useTranslations } from "next-intl";

import { useAgents } from "@/hooks";
import { AgentAvatar } from "@/components/agents/agent-avatar";
import { runsHref } from "@/lib/runs/filter-params";
import { BarList } from "../primitives/bar-list";
import { WidgetFrame } from "../widget-frame";
import type { DashboardWidgetProps } from "./types";
import { UsageBody } from "./usage-body";

/**
 * Which agents carry the traffic - and which published ones nobody ran.
 * The idle list is the half that prompts action: an adopted agent needs
 * nothing, a forgotten one needs either users or archiving.
 */
export function AgentsAdoptionWidget({
  title,
  hint,
  period,
  seeAll,
  options,
}: DashboardWidgetProps) {
  const t = useTranslations("dashboard.widgets.agents");
  const { agents } = useAgents();

  return (
    <WidgetFrame title={title} hint={hint} seeAll={seeAll} options={options}>
      <UsageBody period={period} emptyKey="agents" options={options}>
        {(usage) => {
          const byAgent = usage.by_agent ?? [];
          const ran = new Set(byAgent.map((row) => row.agent_id));
          const idle = agents
            .filter((agent) => agent.status === "published" && !ran.has(agent.id))
            .map((agent) => agent.name);
          // Whether an agent has a picture is not in the usage response - the
          // catalog this card already loads for its idle half knows, so the
          // join is free and the card asks for nothing more.
          const hasAvatar = new Map(agents.map((agent) => [agent.id, agent.has_avatar ?? false]));
          return (
            <div className="flex h-full flex-col justify-between gap-3">
              <BarList
                items={byAgent.slice(0, 5).map((row) => ({
                  label: row.name,
                  value: row.runs,
                  href: runsHref({ period, agentId: row.agent_id }),
                  icon: (
                    <AgentAvatar
                      agentId={row.agent_id}
                      name={row.name}
                      hasAvatar={hasAvatar.get(row.agent_id) ?? false}
                      size="sm"
                      className="h-5 w-5"
                    />
                  ),
                }))}
              />
              {idle.length > 0 ? (
                <p className="text-muted-foreground text-xs">
                  {t("idle")}{" "}
                  {idle.map((name) => (
                    <span
                      key={name}
                      className="bg-warning/12 text-warning mr-1 inline-block rounded-full px-2 py-0.5 whitespace-nowrap"
                    >
                      {name}
                    </span>
                  ))}
                </p>
              ) : null}
            </div>
          );
        }}
      </UsageBody>
    </WidgetFrame>
  );
}
