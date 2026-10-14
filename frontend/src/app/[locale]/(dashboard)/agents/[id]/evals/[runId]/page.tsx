"use client";

import { use } from "react";

import { EvalRunView } from "@/components/evals/eval-run-view";

export default function EvalRunPage({
  params,
}: {
  params: Promise<{ id: string; runId: string }>;
}) {
  const { id, runId } = use(params);
  return <EvalRunView agentId={id} runId={runId} />;
}
