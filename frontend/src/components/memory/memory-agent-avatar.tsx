import { Bot } from "lucide-react";
import { AgentAvatar } from "@/components/agents/agent-avatar";
import type { AgentUsage } from "@/types/agents";

export function MemoryAgentAvatar({ agent }: { agent?: AgentUsage }) {
  if (!agent?.slug) return <Bot className="size-3.5 shrink-0" aria-hidden />;

  return (
    <span aria-hidden className="inline-flex shrink-0">
      <AgentAvatar
        agentId={agent.id}
        slug={agent.slug}
        hasAvatar={agent.has_avatar}
        colorSlot={agent.avatar_color}
        size="sm"
        className="size-5"
      />
    </span>
  );
}
