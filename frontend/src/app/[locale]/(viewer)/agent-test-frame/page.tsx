"use client";

import { useSearchParams } from "next/navigation";

import { TestFrame, testingFromMode } from "@/components/agents/test-panel/test-frame";

/** The agent being built, answering in the Builder's test panel (#2074). */
export default function AgentTestFramePage() {
  const params = useSearchParams();
  const agentId = params.get("agent");
  return agentId ? (
    <TestFrame agentId={agentId} testing={testingFromMode(params.get("mode"))} />
  ) : null;
}
