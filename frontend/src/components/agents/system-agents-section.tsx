"use client";

import type { ReactNode } from "react";
import { useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";

import { useDatasets } from "@/hooks/use-datasets";
import { useSystemAgents } from "@/hooks/use-agents";
import { usePermissions } from "@/hooks/use-permissions";
import type { Agent, SystemAgentKind } from "@/types/agents";
import { Perm, type Permission } from "@/types/permissions";
import { AgentCard } from "./agent-card";
import { CatalogSection } from "./catalog-section";

/** How many datasets a judge's card names before it counts the rest. */
const NAMED = 3;

/** The model a system agent publishes on, or that it has none yet. */
export function SystemAgentModel({ label }: { label: string | null }) {
  const t = useTranslations("agents");
  return (
    <p className="text-muted-foreground truncate font-mono text-xs">{label ?? t("judgeNoModel")}</p>
  );
}

/** Which datasets a judge grades, by name, as far as the caller may see them. */
export function JudgeUsedBy({ judgeId }: { judgeId: string }) {
  const t = useTranslations("agents");
  const { datasets, total, isLoading } = useDatasets({ judge: judgeId, limit: NAMED });
  if (isLoading) return null;
  if (total === 0) return <p className="text-muted-foreground text-xs">{t("judgeUnused")}</p>;
  return (
    <p className="text-muted-foreground truncate text-xs">
      {t("judgeUsedBy", {
        names: datasets.map((dataset) => dataset.name).join(", "),
        more: total - datasets.length,
      })}
    </p>
  );
}

/** What a card says under its model, for the kinds that have more to say. */
const EXTRA_FOOTER: Partial<
  Record<SystemAgentKind, (agent: Agent, can: (permission: Permission) => boolean) => ReactNode>
> = {
  judge: (agent, can) => (can(Perm.datasetsView) ? <JudgeUsedBy judgeId={agent.id} /> : null),
};

interface SystemAgentsSectionProps {
  /** The catalog's search; system agents are narrowed by it too. */
  query: string;
  /** Whether any of the organization's agents matched the search. */
  agentsMatched: boolean;
}

/**
 * The organization's system agents, folded away under its agents, one group per kind.
 *
 * Nobody chats with a system agent, puts it on a channel or delegates to it, so
 * a card carries no menu to duplicate, archive or delete one: `agents:edit`
 * opens it to change its instructions, model and budget. The band remembers
 * being folded, and opens by itself for `?section=system` and for a search only
 * system agents answer. A kind with none is left out, and the band is absent
 * while the organization has none at all.
 */
export function SystemAgentsSection({ query, agentsMatched }: SystemAgentsSectionProps) {
  const t = useTranslations("agents");
  const linked = useSearchParams().get("section") === "system";
  const { groups, total } = useSystemAgents();
  const { can } = usePermissions();
  if (total === 0) return null;
  const needle = query.trim().toLowerCase();
  const shown = groups.map((group) => ({
    ...group,
    agents: group.agents.filter(
      (agent) => needle === "" || agent.name.toLowerCase().includes(needle),
    ),
  }));
  const matched = shown.some((group) => group.agents.length > 0);

  return (
    <CatalogSection
      title={t("systemAgentsCount", { count: total })}
      defaultOpen={false}
      forceOpen={linked || (needle !== "" && !agentsMatched && matched)}
      storageKey="agents.catalog.system"
      tour="agents-system"
    >
      <p className="text-muted-foreground text-xs">{t("systemAgentsHint")}</p>
      {shown
        .filter((group) => group.agents.length > 0)
        .map((group) => (
          <section key={group.kind} className="space-y-2">
            <h3 className="text-sm font-medium">
              {t(`${group.kind}Kind`, { count: group.agents.length })}
            </h3>
            <p className="text-muted-foreground text-xs">{t(`${group.kind}KindHint`)}</p>
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
              {group.agents.map((agent) => (
                <AgentCard
                  key={agent.id}
                  agent={agent}
                  canEdit={can(Perm.agentsEdit)}
                  footer={
                    <>
                      <SystemAgentModel label={agent.published_model?.label ?? null} />
                      {EXTRA_FOOTER[group.kind]?.(agent, can)}
                    </>
                  }
                />
              ))}
            </div>
          </section>
        ))}
    </CatalogSection>
  );
}
