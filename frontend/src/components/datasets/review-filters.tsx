"use client";

import { Check, CircleHelp, Tag, Users, X } from "lucide-react";
import { DatasetChip } from "./dataset-chip";
import { useTranslations } from "next-intl";

import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui";
import { useAgents } from "@/hooks/use-agents";
import { usePermissions } from "@/hooks/use-permissions";
import { Perm } from "@/types/permissions";
import type { ScoreOutcome } from "@/types/scoring";

/** The select's value for "no narrowing". */
const ANY = "any";

export interface ReviewFilter {
  outcome: ScoreOutcome | null;
  agentId: string | null;
  tag: string | null;
}

interface ReviewFiltersProps {
  filter: ReviewFilter;
  onChange: (filter: ReviewFilter) => void;
  /** The dataset's tags, most used first. */
  tags: string[];
}

/** Narrow the dataset's full result list by outcome, agent and tag. */
export function ReviewFilters({ filter, onChange, tags }: ReviewFiltersProps) {
  const t = useTranslations("datasets.scoring");
  const { can } = usePermissions();
  const { agents } = useAgents({ enabled: can(Perm.agentsView) });
  const set = (patch: Partial<ReviewFilter>) => onChange({ ...filter, ...patch });

  return (
    <div className="flex flex-wrap items-center gap-2" data-tour="datasets-review-filter">
      <Select
        value={filter.outcome ?? ANY}
        onValueChange={(value) => set({ outcome: value === ANY ? null : (value as ScoreOutcome) })}
      >
        <SelectTrigger size="sm" className="w-full sm:w-44" aria-label={t("filterOutcome")}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={ANY}>{t("anyOutcome")}</SelectItem>
          <SelectItem value="failed" textValue={t("failed")}>
            <DatasetChip tone="red" icon={X}>
              {t("failed")}
            </DatasetChip>
          </SelectItem>
          <SelectItem value="not_graded" textValue={t("unscored")}>
            <DatasetChip tone="yellow" icon={CircleHelp}>
              {t("unscored")}
            </DatasetChip>
          </SelectItem>
          <SelectItem value="passed" textValue={t("passed")}>
            <DatasetChip tone="green" icon={Check}>
              {t("passed")}
            </DatasetChip>
          </SelectItem>
        </SelectContent>
      </Select>
      {agents.length > 0 && (
        <Select
          value={filter.agentId ?? ANY}
          onValueChange={(value) => set({ agentId: value === ANY ? null : value })}
        >
          <SelectTrigger
            icon={Users}
            size="sm"
            className="w-full sm:w-44"
            aria-label={t("filterAgent")}
          >
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ANY}>{t("anyAgent")}</SelectItem>
            {agents.map((agent) => (
              <SelectItem key={agent.id} value={agent.id}>
                {agent.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      )}
      {tags.length > 0 && (
        <Select
          value={filter.tag ?? ANY}
          onValueChange={(value) => set({ tag: value === ANY ? null : value })}
        >
          <SelectTrigger
            icon={Tag}
            size="sm"
            className="w-full sm:w-36"
            aria-label={t("filterTag")}
          >
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ANY}>{t("anyTag")}</SelectItem>
            {tags.map((tag) => (
              <SelectItem key={tag} value={tag}>
                {tag}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      )}
    </div>
  );
}
