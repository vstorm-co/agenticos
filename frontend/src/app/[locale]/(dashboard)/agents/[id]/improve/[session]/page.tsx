"use client";
import { use } from "react";
import { OrdinaryAgentRoute } from "@/components/agents/ordinary-agent-route";
import { ImprovementPage } from "@/components/improvement/improvement-page";
export default function Page({ params }: { params: Promise<{ id: string; session: string }> }) {
  const { id, session } = use(params);
  return (
    <OrdinaryAgentRoute agentId={id}>
      <ImprovementPage agentId={id} sessionId={session} />
    </OrdinaryAgentRoute>
  );
}
