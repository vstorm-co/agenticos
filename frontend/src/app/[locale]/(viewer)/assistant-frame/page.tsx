"use client";

import { useSearchParams } from "next/navigation";

import { AssistantFrame } from "@/components/assistant/assistant-frame";

/** The AI Architect's conversation, framed by the console's corner widget (#2063). */
export default function AssistantFramePage() {
  const agentId = useSearchParams().get("agent");
  return agentId ? <AssistantFrame agentId={agentId} /> : null;
}
