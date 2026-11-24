"use client";

import { useParams } from "next/navigation";

import { useAgents } from "@/hooks/use-agents";
import { useArtifact } from "@/hooks/use-artifacts";
import { pageOf } from "@/lib/assistant-bubbles";
import { usePathname } from "@/lib/locale-navigation";
import type { Agent } from "@/types/agents";

import { AssistantWidget } from "./assistant-widget";

export function viewerChatAgentId(
  publisherId: string | null | undefined,
  agents: Pick<Agent, "id" | "status" | "can_run">[],
  fallback: string | null,
): string | null {
  return publisherId &&
    agents.some(
      (agent) => agent.id === publisherId && agent.status === "published" && agent.can_run,
    )
    ? publisherId
    : fallback;
}

export function ViewerAssistantWidget() {
  const pathname = usePathname();
  const page = pageOf(pathname);
  const params = useParams<{ id?: string }>();
  if (!page.startsWith("/apps/") || !params.id) return null;
  return <AppAssistantWidget artifactId={params.id} />;
}

function AppAssistantWidget({ artifactId }: { artifactId: string }) {
  const { artifact, isLoading: artifactLoading } = useArtifact(artifactId);
  const { agents, isLoading: agentsLoading } = useAgents({ includeArchived: true });
  if (artifactLoading || agentsLoading) return null;

  return (
    <AssistantWidget defaultAgentId={viewerChatAgentId(artifact?.agent_id, agents, null)} viewer />
  );
}
