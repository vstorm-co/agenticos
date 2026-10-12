"use client";

import { useEffect, useRef, useState } from "react";
import { Ban, HelpCircle, Pin, UserRound } from "lucide-react";
import { useTranslations } from "next-intl";

import { AgentAvatar } from "@/components/agents/agent-avatar";
import { ChatContainer, type ChatPrompt } from "@/components/chat/chat-container";
import { ChatWelcome, type WelcomeSuggestion } from "@/components/chat/chat-welcome";
import { useAgent } from "@/hooks/use-agents";
import type { ChatTesting } from "@/hooks/use-chat";
import { useChatStore } from "@/stores";

/** The questions worth asking any agent under test, before its own pinned ones exist. */
const STARTERS = [
  { key: "Scope", icon: HelpCircle },
  { key: "OffTopic", icon: Ban },
  { key: "Identity", icon: UserRound },
] as const;

interface TestChatProps {
  agentId: string;
  testing: ChatTesting;
  /** The panel's pinned questions, which it keeps per agent. */
  pinned: readonly string[];
  /** Pin a question from the conversation, or take it off. */
  onTogglePin: (text: string) => void;
  /** A question the panel asked - the compare box, sent to both conversations. */
  ask: ChatPrompt | null;
  /** Bumped to send the last question again. */
  replay: number;
}

/**
 * The agent being built, answering in the Builder's test panel (#2074).
 *
 * The console's own chat, in the `ChatScope` the panel gives it, so its stores
 * and socket are not the main chat's. Every turn is a test run of the draft or
 * of one environment's version. The panel starts a new conversation by giving
 * the scope a new key.
 *
 * It opens as `/chat` does (#2075): the agent's face and what answers, then its
 * pinned questions and a few any agent should be asked.
 */
export function TestChat({ agentId, testing, pinned, onTogglePin, ask, replay }: TestChatProps) {
  const t = useTranslations("agents");
  const { agent } = useAgent(agentId);
  const chatApi = useChatStore.useApi();
  const [prompt, setPrompt] = useState<ChatPrompt | null>(null);
  const sent = useRef(0);
  // What the panel had already asked when this conversation began - a new
  // conversation is a new scope, and must not send the last one's question again.
  const heardAsk = useRef(ask);
  const heardReplay = useRef(replay);

  useEffect(() => {
    if (ask === null || ask === heardAsk.current) return;
    heardAsk.current = ask;
    sent.current += 1;
    setPrompt({ id: sent.current, text: ask.text });
  }, [ask]);

  useEffect(() => {
    if (replay === heardReplay.current) return;
    heardReplay.current = replay;
    const text = chatApi.getState().messages.findLast((entry) => entry.role === "user")?.content;
    if (!text) return;
    sent.current += 1;
    setPrompt({ id: sent.current, text });
  }, [replay, chatApi]);

  const suggestions: WelcomeSuggestion[] = [
    ...pinned.map((text) => ({
      key: `pinned:${text}`,
      icon: Pin,
      title: text,
      prompt: text,
      description: t("testPinnedHint"),
      onRemove: () => onTogglePin(text),
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
          pins={{ pinned, toggle: onTogglePin }}
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

/** What a panel choice says should answer: `draft`, an environment id, or the default. */
export function testingFromMode(mode: string | null): ChatTesting {
  if (mode === "draft") return { draft: true, environmentId: null };
  return { draft: false, environmentId: mode && mode !== "default" ? mode : null };
}
