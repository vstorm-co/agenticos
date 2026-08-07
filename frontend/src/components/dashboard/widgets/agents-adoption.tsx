"use client";

import { useTranslations } from "next-intl";

import { useAgents } from "@/hooks";
import { BarList } from "../primitives/bar-list";
import { WidgetFrame } from "../widget-frame";
import type { DashboardWidgetProps } from "./types";
import { UsageBody } from "./usage-body";

/**
 * Which agents carry the traffic - and which published ones nobody ran.
 * The idle list is the half that prompts action: an adopted agent needs
 * nothing, a forgotten one needs either users or archiving.
 */
export function AgentsAdoptionWidget({ title, period, seeAll }: DashboardWidgetProps) {
  const t = useTranslations("dashboard.widgets.agents");
  const { agents } = useAgents();

  return (
    <WidgetFrame title={title} seeAll={seeAll}>
      <UsageBody period={period} emptyKey="agents">
        {(usage) => {
          const byAgent = usage.by_agent ?? [];
          const ran = new Set(byAgent.map((row) => row.agent_id));
          const idle = agents
            .filter((agent) => agent.status === "published" && !ran.has(agent.id))
            .map((agent) => agent.name);
          return (
            <div className="flex h-full flex-col justify-between gap-3">
              <BarList
                items={byAgent.slice(0, 5).map((row) => ({ label: row.name, value: row.runs }))}
              />
              {idle.length > 0 ? (
                <p className="text-muted-foreground text-xs">
                  {t("idle")}{" "}
                  {idle.map((name) => (
                    <span
                      key={name}
                      className="text-warning border-warning/30 mr-1 inline-block rounded-full border px-2 py-0.5 whitespace-nowrap"
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
