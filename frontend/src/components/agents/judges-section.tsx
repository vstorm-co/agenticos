"use client";

import { useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";

import { useDatasets } from "@/hooks/use-datasets";
import { useJudges } from "@/hooks/use-agents";
import { usePermissions } from "@/hooks/use-permissions";
import { Perm } from "@/types/permissions";
import { AgentCard } from "./agent-card";
import { CatalogSection } from "./catalog-section";

/** How many datasets a judge's card names before it counts the rest. */
const NAMED = 3;

/** The model a judge publishes on, or that it has none yet. */
export function JudgeModel({ label }: { label: string | null }) {
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

interface JudgesSectionProps {
  /** The catalog's search; judges are narrowed by it too. */
  query: string;
  /** Whether any of the organization's agents matched the search. */
  agentsMatched: boolean;
}

/**
 * The organization's judges, folded away under its agents.
 *
 * Nobody chats with a judge, puts it on a channel or delegates to it, so a card
 * carries no menu to duplicate, archive or delete one: `agents:edit` opens it to
 * change its instructions, model and budget. The band remembers being folded,
 * and opens by itself for `?section=judges` and for a search only judges answer.
 * Absent while the organization has none.
 */
export function JudgesSection({ query, agentsMatched }: JudgesSectionProps) {
  const t = useTranslations("agents");
  const linked = useSearchParams().get("section") === "judges";
  const { agents, total } = useJudges();
  const { can } = usePermissions();
  if (total === 0) return null;
  const needle = query.trim().toLowerCase();
  const shown = agents.filter(
    (agent) => needle === "" || agent.name.toLowerCase().includes(needle),
  );

  return (
    <CatalogSection
      title={t("judgesCount", { count: total })}
      defaultOpen={false}
      forceOpen={linked || (needle !== "" && !agentsMatched && shown.length > 0)}
      storageKey="agents.catalog.judges"
      tour="agents-judges"
    >
      <p className="text-muted-foreground text-xs">{t("judgesHint")}</p>
      <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
        {shown.map((agent) => (
          <AgentCard
            key={agent.id}
            agent={agent}
            canEdit={can(Perm.agentsEdit)}
            footer={
              <>
                <JudgeModel label={agent.published_model?.label ?? null} />
                {can(Perm.datasetsView) && <JudgeUsedBy judgeId={agent.id} />}
              </>
            }
          />
        ))}
      </div>
    </CatalogSection>
  );
}
