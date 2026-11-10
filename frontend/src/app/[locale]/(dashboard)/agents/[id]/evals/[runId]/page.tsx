"use client";

import { use } from "react";

import { OrdinaryAgentRoute } from "@/components/agents/ordinary-agent-route";
import { EvalRunView } from "@/components/evals/eval-run-view";

export default function EvalRunPage({
  params,
}: {
  params: Promise<{ id: string; runId: string }>;
}) {
  const { id, runId } = use(params);
  return (
    <OrdinaryAgentRoute agentId={id}>
      <EvalRunView agentId={id} runId={runId} />
    </OrdinaryAgentRoute>
  );
}
