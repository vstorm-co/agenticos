"use client";

import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { Ban, HelpCircle, Pin, UserRound } from "lucide-react";
import { useTranslations } from "next-intl";

import { AgentAvatar } from "@/components/agents/agent-avatar";
import { ChatContainer, type ChatPrompt } from "@/components/chat/chat-container";
import { ChatWelcome, type WelcomeSuggestion } from "@/components/chat/chat-welcome";
import { useAgent } from "@/hooks/use-agents";
import type { ChatTesting } from "@/hooks/use-chat";
import { useConversations } from "@/hooks/use-conversations";
import { ASK, NEW, PIN, readToFrame, REPLAY } from "@/lib/assistant-messages";
import { readTestPanel } from "@/lib/test-panel-state";
import { useAgentSelectionStore, useChatStore } from "@/stores";

/** The questions worth asking any agent under test, before its own pinned ones exist. */
const STARTERS = [
  { key: "Scope", icon: HelpCircle },
  { key: "OffTopic", icon: Ban },
  { key: "Identity", icon: UserRound },
] as const;

/**
 * The agent being built, answering in the Builder's test panel (#2074).
 *
 * The whole chat - streaming, tool steps, approval cards, questions, files - in a
 * document of its own, so its stores and socket are not the main chat's. Every
 * turn is a test run of the draft or of one environment's version. The Builder
 * drives it with messages: a pinned prompt, a new conversation, a replay.
 *
 * It opens as `/chat` does (#2075): the agent's face and what answers, then its
 * pinned questions and a few any agent should be asked. A question is pinned
 * from the conversation itself, and the panel - which keeps the list - is told.
 */
export function TestFrame({ agentId, testing }: { agentId: string; testing: ChatTesting }) {
  const t = useTranslations("agents");
  const select = useAgentSelectionStore((state) => state.select);
  const { startNewChat } = useConversations({ agentId });
  const { agent } = useAgent(agentId);
  const pinned = usePinned(agentId);
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

  const togglePin = (text: string) =>
    window.parent.postMessage({ type: PIN, text }, window.location.origin);

  const suggestions: WelcomeSuggestion[] = [
    ...pinned.map((text) => ({
      key: `pinned:${text}`,
      icon: Pin,
      title: text,
      prompt: text,
      description: t("testPinnedHint"),
      onRemove: () => togglePin(text),
    })),
    ...STARTERS.map(({ key, icon }) => ({
      key,
      icon,
      title: t(`testStarter${key}Title`),
      prompt: t(`testStarter${key}Prompt`),
    })),
  ];

  return (
    <div className="flex min-h-0 flex-1">
      <div className="min-w-0 flex-1">
        <ChatContainer
          prompt={prompt}
          agentFixed
          testing={testing}
          pins={{ pinned, toggle: togglePin }}
          emptyState={(onPick) => (
            <ChatWelcome
              compact
              mark={
                agent ? (
                  <AgentAvatar
                    agentId={agent.id}
                    slug={agent.slug}
                    hasAvatar={agent.has_avatar ?? false}
                    colorSlot={agent.avatar_color}
                    size="lg"
                  />
                ) : null
              }
              title={t("testWelcomeTitle", { name: agent?.name ?? "" })}
              lead={testing.draft ? t("testWelcomeDraft") : t("testWelcomeVersion")}
              suggestions={suggestions}
              onPick={onPick}
            />
          )}
        />
      </div>
    </div>
  );
}

/**
 * The panel's pinned questions, as the panel last stored them.
 *
 * Read from the panel's own storage and followed through `storage` events, which
 * reach this frame whenever the panel - another document - writes it.
 */
function usePinned(agentId: string): readonly string[] {
  // The same array for the same list, as `useSyncExternalStore` requires: a new
  // one on every read would render for ever.
  const last = useRef<readonly string[]>([]);
  return useSyncExternalStore(
    (onChange) => {
      window.addEventListener("storage", onChange);
      return () => window.removeEventListener("storage", onChange);
    },
    () => {
      const pinned = readTestPanel(agentId).pinned;
      const same =
        pinned.length === last.current.length &&
        pinned.every((text, index) => text === last.current[index]);
      if (!same) last.current = pinned;
      return last.current;
    },
    () => last.current,
  );
}

/** What the frame's address says should answer: `draft`, an environment id, or the default. */
export function testingFromMode(mode: string | null): ChatTesting {
  if (mode === "draft") return { draft: true, environmentId: null };
  return { draft: false, environmentId: mode && mode !== "default" ? mode : null };
}
