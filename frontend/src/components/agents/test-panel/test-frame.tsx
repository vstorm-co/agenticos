"use client";

import { useEffect, useState } from "react";

import { ChatContainer, type ChatPrompt } from "@/components/chat/chat-container";
import type { ChatTesting } from "@/hooks/use-chat";
import { useConversations } from "@/hooks/use-conversations";
import { ASK, NEW, readToFrame, REPLAY } from "@/lib/assistant-messages";
import { useAgentSelectionStore, useChatStore } from "@/stores";

/**
 * The agent being built, answering in the Builder's test panel (#2074).
 *
 * The whole chat - streaming, tool steps, approval cards, questions, files - in a
 * document of its own, so its stores and socket are not the main chat's. Every
 * turn is a test run of the draft or of one environment's version. The Builder
 * drives it with messages: a pinned prompt, a new conversation, a replay.
 */
export function TestFrame({ agentId, testing }: { agentId: string; testing: ChatTesting }) {
  const select = useAgentSelectionStore((state) => state.select);
  const { startNewChat } = useConversations({ agentId });
  const [prompt, setPrompt] = useState<ChatPrompt | null>(null);

  useEffect(() => {
    select(agentId);
  }, [agentId, select]);

  useEffect(() => {
    let sent = 0;
    const onMessage = (event: MessageEvent) => {
      const message = readToFrame(event, window.location.origin);
      if (message === null) return;
      if (message.type === NEW) {
        void startNewChat();
        return;
      }
      const text =
        message.type === ASK
          ? message.text
          : message.type === REPLAY
            ? useChatStore.getState().messages.findLast((entry) => entry.role === "user")?.content
            : undefined;
      if (text) {
        sent += 1;
        setPrompt({ id: sent, text });
      }
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [startNewChat]);

  return (
    <div className="flex min-h-0 flex-1">
      <div className="min-w-0 flex-1">
        <ChatContainer prompt={prompt} agentFixed testing={testing} />
      </div>
    </div>
  );
}

/** What the frame's address says should answer: `draft`, an environment id, or the default. */
export function testingFromMode(mode: string | null): ChatTesting {
  if (mode === "draft") return { draft: true, environmentId: null };
  return { draft: false, environmentId: mode && mode !== "default" ? mode : null };
}
