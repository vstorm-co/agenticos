"use client";

import { CalendarClock, Compass, FileSearch, Mail, MessageSquare, Sparkles } from "lucide-react";

import { useTranslations } from "next-intl";

import { AgentAvatar } from "@/components/agents/agent-avatar";
import { useAgents, useAuth } from "@/hooks";
import { useAgentSelectionStore } from "@/stores";

import { ChatWelcome, WelcomeIcon, type WelcomeSuggestion } from "./chat-welcome";

/**
 * The four openers for an agent that names none of its own, in order. Their
 * words live in the catalog under `empty.<id>*`. Two of them show what an agent
 * here does beyond answering - say what it can, and run on a schedule (#2301).
 */
const PROMPTS = [
  { icon: Compass, id: "capabilities" },
  { icon: FileSearch, id: "docs" },
  { icon: CalendarClock, id: "routine" },
  { icon: Mail, id: "email" },
] as const;

interface ChatEmptyStateProps {
  onPick: (prompt: string) => void;
}

export function ChatEmptyState({ onPick }: ChatEmptyStateProps) {
  const t = useTranslations("chat.empty");
  const { user } = useAuth();
  const firstName = user?.full_name?.split(" ")[0] || user?.email?.split("@")[0];
  // Whoever will answer, so the page opens on them rather than on a generic
  // sparkle and a line about streaming and tool calls. The list is the one the
  // picker already holds.
  const selectedAgentId = useAgentSelectionStore((state) => state.selectedAgentId);
  const { agents } = useAgents({ includeArchived: true });
  const agent = agents.find((candidate) => candidate.id === selectedAgentId);
  const description = agent?.description?.trim();
  // The agent's own first messages, as its published version names them, in
  // the words its author wrote - the card is the message, so nothing under it.
  const starters = agent?.starters ?? [];
  const suggestions: WelcomeSuggestion[] = starters.length
    ? starters.map((starter, index) => ({
        key: `starter-${index}`,
        icon: MessageSquare,
        title: starter,
        prompt: starter,
        description: "",
      }))
    : PROMPTS.map((p) => ({
        key: p.id,
        icon: p.icon,
        title: t(`${p.id}Title`),
        prompt: t(`${p.id}Prompt`),
      }));

  return (
    <ChatWelcome
      mark={
        agent ? (
          <AgentAvatar
            agentId={agent.id}
            slug={agent.slug}
            hasAvatar={agent.has_avatar}
            colorSlot={agent.avatar_color}
            size="lg"
          />
        ) : (
          <WelcomeIcon icon={Sparkles} />
        )
      }
      title={firstName ? t("greeting", { name: firstName }) : t("greetingAnonymous")}
      lead={
        agent ? (
          <>
            <span className="text-foreground font-medium">{agent.name}</span>
            {description ? ` · ${description}` : ""}
          </>
        ) : (
          t("lead")
        )
      }
      suggestions={suggestions}
      onPick={onPick}
      footer={
        <>
          <kbd className="border-border bg-card rounded px-1.5 py-0.5 font-mono text-xs">⌘K</kbd>
          <span>{t("commandPalette")}</span>
          <span className="text-border">·</span>
          <kbd className="border-border bg-card rounded px-1.5 py-0.5 font-mono text-xs">/</kbd>
          <span>{t("slashCommands")}</span>
        </>
      }
    />
  );
}
