"use client";

import { AgentAvatar } from "@/components/agents/agent-avatar";
import { useAgents } from "@/hooks";

/**
 * An agent's picture from its id alone, for a card whose rows name an agent by
 * id - an approval, a failure, a usage row - and nothing else about it.
 *
 * The handle the face is drawn from, and whether a picture was uploaded, come
 * from the agents list the dashboard already holds, so a card asks for nothing
 * more. An agent the reader can no longer see still gets a face, drawn from its
 * id, rather than a gap in the row.
 */
export function AgentFace({ agentId, className }: { agentId: string; className?: string }) {
  const { agents } = useAgents();
  const agent = agents.find((candidate) => candidate.id === agentId);
  return (
    <AgentAvatar
      agentId={agentId}
      slug={agent?.slug ?? agentId}
      hasAvatar={agent?.has_avatar ?? false}
      colorSlot={agent?.avatar_color}
      size="sm"
      className={className}
    />
  );
}
