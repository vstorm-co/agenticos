"use client";

import { useTranslations } from "next-intl";

import { useDatasets } from "@/hooks/use-datasets";
import { useJudges } from "@/hooks/use-agents";
import { usePermissions } from "@/hooks/use-permissions";
import { Perm } from "@/types/permissions";
import { AgentCard } from "./agent-card";
import { CatalogSection } from "./catalog-section";

/** How many datasets a judge's card names before it counts the rest. */
const NAMED = 3;

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

/**
 * The organization's judges, folded away under its agents.
 *
 * Nobody chats with a judge, puts it on a channel or delegates to it, so a card
 * carries no menu to duplicate, archive or delete one: `agents:edit` opens it to
 * change its instructions, model and budget. Absent while the organization has none.
 */
export function JudgesSection() {
  const t = useTranslations("agents");
  const { agents, total } = useJudges();
  const { can } = usePermissions();
  if (total === 0) return null;

  return (
    <CatalogSection
      title={t("judgesCount", { count: total })}
      defaultOpen={false}
      tour="agents-judges"
    >
      <p className="text-muted-foreground text-xs">{t("judgesHint")}</p>
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
        {agents.map((agent) => (
          <AgentCard
            key={agent.id}
            agent={agent}
            canEdit={can(Perm.agentsEdit)}
            footer={can(Perm.datasetsView) ? <JudgeUsedBy judgeId={agent.id} /> : undefined}
          />
        ))}
      </div>
    </CatalogSection>
  );
}
