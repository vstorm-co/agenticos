"use client";

import { useEffect, useState } from "react";

import { ChatContainer, type ChatPrompt } from "@/components/chat/chat-container";
import { useAssistant } from "@/hooks/use-assistant";
import { useConversations } from "@/hooks/use-conversations";
import { ASK, CONTEXT, NEW, readToFrame } from "@/lib/assistant-messages";
import { useAgentSelectionStore } from "@/stores";

import { AssistantHistory } from "./assistant-history";
import { AssistantWelcome, type PageContext } from "./assistant-welcome";

/**
 * The AI Architect's conversation, inside the corner widget's frame (#2063).
 *
 * The whole chat - streaming, approval cards, the question carousel, files -
 * addressed to the assistant, in a document of its own so its stores and its
 * socket are not the main chat's. The console drives it with messages: a prompt
 * a bubble asked, the page the reader is on, a new conversation, the history.
 */
export function AssistantFrame({ agentId }: { agentId: string }) {
  const { assistant } = useAssistant();
  const select = useAgentSelectionStore((state) => state.select);
  const { startNewChat } = useConversations({ agentId });
  const [prompt, setPrompt] = useState<ChatPrompt | null>(null);
  const [page, setPage] = useState<PageContext | null>(null);
  const [showHistory, setShowHistory] = useState(false);

  useEffect(() => {
    select(agentId);
  }, [agentId, select]);

  useEffect(() => {
    let asked = 0;
    const onMessage = (event: MessageEvent) => {
      const message = readToFrame(event, window.location.origin);
      if (message === null) return;
      if (message.type === ASK) {
        asked += 1;
        setPrompt({ id: asked, text: message.text });
      } else if (message.type === CONTEXT) {
        setPage({ path: message.path, title: message.title });
      } else if (message.type === NEW) {
        setShowHistory(false);
        void startNewChat();
      } else {
        setShowHistory((open) => !open);
      }
    };
    window.addEventListener("message", onMessage);
    return () => window.removeEventListener("message", onMessage);
  }, [startNewChat]);

  return (
    <div className="relative flex min-h-0 flex-1">
      {showHistory && <AssistantHistory agentId={agentId} onClose={() => setShowHistory(false)} />}
      <div className="min-w-0 flex-1">
        <ChatContainer
          prompt={prompt}
          agentFixed
          emptyState={(onPick) =>
            assistant && (
              <AssistantWelcome
                greeting={assistant.greeting}
                name={assistant.name}
                page={page}
                onPick={onPick}
              />
            )
          }
        />
      </div>
    </div>
  );
}
