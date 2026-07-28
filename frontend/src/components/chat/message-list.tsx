"use client";

import { useMemo } from "react";

import { useAgents } from "@/hooks";
import type { ChatMessage } from "@/types";
import { MessageItem } from "./message-item";

interface MessageListProps {
  messages: ChatMessage[];
  onRegenerate?: (messageId: string) => void;
}

export function MessageList({ messages, onRegenerate }: MessageListProps) {
  // Agents are resolved here rather than stamped onto the message, so a renamed
  // agent is labelled by its current name and a new picture appears on old
  // turns. The query is the one the agent picker already made, so this costs a
  // cache read. Archived agents are included: a conversation that an agent took
  // part in before it was retired still has to say who answered.
  const { agents } = useAgents({ includeArchived: true });
  const byId = useMemo(() => new Map(agents.map((agent) => [agent.id, agent])), [agents]);

  const getGroupPosition = (
    message: ChatMessage,
  ): "first" | "middle" | "last" | "single" | undefined => {
    if (!message.groupId) return undefined;

    const groupMessages = messages.filter((m) => m.groupId === message.groupId);
    if (groupMessages.length <= 1) return "single";

    const groupIndex = groupMessages.findIndex((m) => m.id === message.id);
    if (groupIndex === 0) return "first";
    if (groupIndex === groupMessages.length - 1) return "last";
    return "middle";
  };

  // Only allow regenerating the most recent assistant message - older ones
  // would diverge the transcript in a confusing way.
  const lastAssistantIndex = (() => {
    for (let i = messages.length - 1; i >= 0; i--) {
      if (messages[i]?.role === "assistant") return i;
    }
    return -1;
  })();

  return (
    <div className="space-y-0">
      {messages.map((message, index) => (
        <MessageItem
          key={message.id}
          message={message}
          agent={message.agentId ? byId.get(message.agentId) : undefined}
          groupPosition={getGroupPosition(message)}
          onRegenerate={
            onRegenerate && index === lastAssistantIndex && !message.isStreaming
              ? () => onRegenerate(message.id)
              : undefined
          }
        />
      ))}
    </div>
  );
}
