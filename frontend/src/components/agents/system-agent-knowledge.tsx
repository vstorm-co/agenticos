"use client";

import { useTranslations } from "next-intl";

import { Input, Label } from "@/components/ui";
import { SYSTEM_AGENT_MAX_STEPS, SYSTEM_AGENT_SEARCH_STEPS } from "@/lib/system-agents";
import type { SystemAgentKind } from "@/types/agents";

/**
 * What a system agent's Knowledge panel sets in place of the collections an
 * ordinary agent picks there.
 */
export interface SystemAgentSearch {
  /** Which system agent it is, which decides what a search gives it. */
  kind: SystemAgentKind;
  /** `spec.max_steps`; unset runs a search in `SYSTEM_AGENT_SEARCH_STEPS`. */
  maxSteps: number | null | undefined;
  /** Writes `spec.max_steps`, null clearing it. */
  onMaxSteps: (maxSteps: number | null) => void;
}

/**
 * How a system agent searches a knowledge base while it works.
 *
 * There is no collection to pick: the platform hands each run the knowledge
 * bases it is about - the graded agent's, the gap's, the ones a generation
 * drafts from - which is why the sentence changes with the kind. What is left to
 * decide is how many steps a search may take.
 */
export function SystemAgentKnowledge({
  search,
  disabled,
}: {
  search: SystemAgentSearch;
  disabled?: boolean;
}) {
  const t = useTranslations("agents");

  return (
    <section className="space-y-3">
      <p className="text-muted-foreground text-xs">
        {t("systemAgentKnowledgeHelp", { kind: search.kind })}
      </p>
      <div className="space-y-2">
        <Label htmlFor="system-agent-max-steps">{t("systemAgentMaxSteps")}</Label>
        <Input
          id="system-agent-max-steps"
          type="number"
          step="1"
          min="1"
          max={SYSTEM_AGENT_MAX_STEPS}
          value={search.maxSteps ?? ""}
          disabled={disabled}
          placeholder={String(SYSTEM_AGENT_SEARCH_STEPS)}
          aria-describedby="system-agent-max-steps-hint"
          className="max-w-32"
          onChange={(event) =>
            search.onMaxSteps(event.target.value ? Number(event.target.value) : null)
          }
        />
        <p id="system-agent-max-steps-hint" className="text-muted-foreground text-xs">
          {t("systemAgentMaxStepsHint", {
            max: SYSTEM_AGENT_MAX_STEPS,
            fallback: SYSTEM_AGENT_SEARCH_STEPS,
          })}
        </p>
      </div>
    </section>
  );
}
