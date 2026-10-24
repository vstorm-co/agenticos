"use client";

import { useTranslations } from "next-intl";

import {
  Button,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { useAgents } from "@/hooks/use-agents";
import { usePermissions } from "@/hooks/use-permissions";
import { cn } from "@/lib/utils";
import { Perm } from "@/types/permissions";
import type { ScoreOutcome } from "@/types/scoring";

/** The select's value for "no narrowing". */
const ANY = "any";

export interface ReviewFilter {
  pending: boolean;
  outcome: ScoreOutcome | null;
  agentId: string | null;
  tag: string | null;
}

interface ReviewFiltersProps {
  filter: ReviewFilter;
  onChange: (filter: ReviewFilter) => void;
  /** How many results wait for a decision, and how many there are in all, under the filters. */
  waiting: number;
  all: number;
  /** The dataset's tags, most used first. */
  tags: string[];
}

/**
 * What the Review tab shows: the waiting results or all of them, each with its
 * count, narrowed by outcome, by the agent that answered and by a tag of the case.
 */
export function ReviewFilters({ filter, onChange, waiting, all, tags }: ReviewFiltersProps) {
  const t = useTranslations("datasets.scoring");
  const { can } = usePermissions();
  const { agents } = useAgents({ enabled: can(Perm.agentsView) });
  const set = (patch: Partial<ReviewFilter>) => onChange({ ...filter, ...patch });

  return (
    <div className="flex flex-wrap items-center gap-2" data-tour="datasets-review-filter">
      <div role="group" aria-label={t("reviewFilter")} className="flex rounded-md border p-0.5">
        {([true, false] as const).map((pending) => (
          <Button
            key={String(pending)}
            size="sm"
            variant="ghost"
            aria-pressed={filter.pending === pending}
            className={cn(filter.pending === pending && "bg-muted")}
            onClick={() => set({ pending })}
          >
            {pending ? t("filterPending", { count: waiting }) : t("filterAll", { count: all })}
          </Button>
        ))}
      </div>
      <Select
        value={filter.outcome ?? ANY}
        onValueChange={(value) => set({ outcome: value === ANY ? null : (value as ScoreOutcome) })}
      >
        <SelectTrigger className="w-40" aria-label={t("filterOutcome")}>
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value={ANY}>{t("anyOutcome")}</SelectItem>
          <SelectItem value="failed">{t("failed")}</SelectItem>
          <SelectItem value="not_graded">{t("unscored")}</SelectItem>
          <SelectItem value="passed">{t("passed")}</SelectItem>
        </SelectContent>
      </Select>
      {agents.length > 0 && (
        <Select
          value={filter.agentId ?? ANY}
          onValueChange={(value) => set({ agentId: value === ANY ? null : value })}
        >
          <SelectTrigger className="w-44" aria-label={t("filterAgent")}>
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
          <SelectTrigger className="w-36" aria-label={t("filterTag")}>
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
