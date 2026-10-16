"use client";

import { useMemo } from "react";

import { specText } from "@/components/agents/version-history";
import { useAgent, useAgentVersion } from "@/hooks";
import { usePermissions } from "@/hooks/use-permissions";
import type { EvalRunRequest } from "@/types/eval-runs";
import { Perm } from "@/types/permissions";

/**
 * What a run tests: the draft against what is live, what is live alone, or the
 * draft alone - the only choice an agent nobody published has.
 */
export type EvalTarget = "compare" | "version" | "draft";

export const TARGET_REQUEST: Record<
  EvalTarget,
  Pick<EvalRunRequest, "candidate" | "paired_baseline">
> = {
  compare: { candidate: "draft", paired_baseline: true },
  version: { candidate: "version", paired_baseline: false },
  draft: { candidate: "draft", paired_baseline: false },
};

/**
 * The agent a run would test, read for the choices the dialog offers: which
 * version is live, whether the draft differs from it, and whether the caller
 * may run the draft at all - the editors' work in progress.
 */
export function useEvalTarget(agentId: string | null) {
  const { agent } = useAgent(agentId);
  const { version } = useAgentVersion(agentId, agent?.current_version_id ?? null);
  const { can } = usePermissions();
  const canRunDraft = can(Perm.agentsEdit);
  const draftDiffers = useMemo(
    () => (agent && version ? specText(agent.draft_spec) !== specText(version.spec) : false),
    [agent, version],
  );
  const currentVersion = version?.version ?? null;
  const targets: EvalTarget[] =
    agent?.current_version_id === null
      ? canRunDraft
        ? ["draft"]
        : []
      : currentVersion === null
        ? []
        : canRunDraft
          ? ["compare", "version"]
          : ["version"];
  // The draft against what is live is the question a change asks; with nothing
  // changed there is nothing to compare, and what is live is what to measure.
  const preferred: EvalTarget | null = targets.includes("compare")
    ? draftDiffers
      ? "compare"
      : "version"
    : (targets[0] ?? null);
  const ready = agent !== undefined && (agent.current_version_id === null || version !== undefined);
  return { agent, currentVersion, targets, preferred: ready ? preferred : null };
}
