"use client";

import { useEffect, useState } from "react";

import { ChatContainer, type ChatPrompt } from "@/components/chat/chat-container";
import type { IncomingFiles } from "@/components/chat/chat-input";
import { useAssistant } from "@/hooks/use-assistant";
import { useConversations } from "@/hooks/use-conversations";
import { consoleLink } from "@/lib/assistant-highlight";
import { ASK, ATTACH, CONTEXT, NAVIGATE, NEW, readToFrame } from "@/lib/assistant-messages";
import { useAgentSelectionStore } from "@/stores";

import { AssistantHistory } from "./assistant-history";
import { AssistantFace } from "./assistant-launcher";
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
  const [incoming, setIncoming] = useState<IncomingFiles | null>(null);

  useEffect(() => {
    select(agentId);
  }, [agentId, select]);

  useEffect(() => {
    let asked = 0;
    let attached = 0;
    const onMessage = (event: MessageEvent) => {
      const message = readToFrame(event, window.location.origin);
      if (message === null) return;
      if (message.type === ASK) {
        asked += 1;
        setPrompt({ id: asked, text: message.text });
      } else if (message.type === CONTEXT) {
        setPage({ path: message.path, title: message.title });
      } else if (message.type === ATTACH) {
        attached += 1;
        setIncoming({ id: attached, files: [message.file] });
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

  // A console link in the conversation opens in the console, not in this
  // frame: "show me where" is about the page behind the window.
  useEffect(() => {
    const onClick = (event: MouseEvent) => {
      const anchor = (event.target as Element | null)?.closest?.("a");
      const href = anchor?.getAttribute("href") ?? null;
      if (consoleLink(href, window.location.origin) === null) return;
      event.preventDefault();
      window.parent.postMessage({ type: NAVIGATE, href }, window.location.origin);
    };
    document.addEventListener("click", onClick, true);
    return () => document.removeEventListener("click", onClick, true);
  }, []);

  return (
    <div className="relative flex min-h-0 flex-1">
      {showHistory && <AssistantHistory agentId={agentId} onClose={() => setShowHistory(false)} />}
      <div className="min-w-0 flex-1">
        <ChatContainer
          prompt={prompt}
          agentFixed
          incomingFiles={incoming}
          emptyState={(onPick) =>
            assistant && (
              <AssistantWelcome
                greeting={assistant.greeting}
                name={assistant.name}
                mark={<AssistantFace assistant={assistant} agentId={agentId} size="lg" />}
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
