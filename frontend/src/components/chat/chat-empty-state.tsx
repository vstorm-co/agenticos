"use client";

import {
  CalendarClock,
  Calculator,
  Compass,
  FileSearch,
  Mail,
  MapPinned,
  MessageSquare,
  Plane,
  Sparkles,
  Table2,
} from "lucide-react";

import { useTranslations } from "next-intl";

import { AgentAvatar } from "@/components/agents/agent-avatar";
import { useAgents, useAuth } from "@/hooks";
import { useMentionables } from "@/hooks/use-mentionables";
import { usePersonalStarters } from "@/hooks/use-suggestions";
import { VISUALS_ID } from "@/lib/agent-spec";
import { useAgentSelectionStore } from "@/stores";

import { ChatWelcome, WelcomeIcon, type WelcomeSuggestion } from "./chat-welcome";
import { SuggestionCards } from "./suggestion-cards";

/** The starter agent, whose empty chat carries what the platform proposes to the person. */
const STARTER_SLUG = "agenticos";

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

/**
 * The openers for an agent that can draw (#2302): one per kind of answer it can
 * give beyond text - explain, compare, make a tool, follow a trip - so the first
 * thing a person sees is what the agent can do. Words under `empty.visual<Id>*`.
 */
const VISUAL_PROMPTS = [
  { icon: Plane, id: "visualExplain" },
  { icon: Table2, id: "visualCompare" },
  { icon: Calculator, id: "visualTool" },
  { icon: MapPinned, id: "visualMap" },
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
  // The list the composer reads for `@`, so it is usually in hand already.
  const { items } = useMentionables(agent ? agent.id : null);
  const draws = items.some((item) => item.kind === "capability" && item.id === VISUALS_ID);
  // The agent's own first messages, as its published version names them, in
  // the words its author wrote - the card is the message, so nothing under it.
  // The starter agent has none and offers the person's own instead, written for
  // them overnight (#2301). Without either, an agent that draws opens on what it
  // can draw (#2302).
  const isStarter = agent?.slug === STARTER_SLUG;
  const own = agent?.starters ?? [];
  const written = usePersonalStarters(isStarter);
  const personal = isStarter ? written : [];
  const starters = own.length ? own : personal;
  const suggestions: WelcomeSuggestion[] = starters.length
    ? starters.map((starter, index) => ({
        key: `starter-${index}`,
        icon: MessageSquare,
        title: starter,
        prompt: starter,
        description: "",
      }))
    : (draws ? VISUAL_PROMPTS : PROMPTS).map((p) => ({
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
      notice={isStarter && agent ? <SuggestionCards agentId={agent.id} /> : undefined}
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
