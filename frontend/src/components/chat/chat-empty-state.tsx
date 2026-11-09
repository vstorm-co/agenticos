"use client";

import { useSyncExternalStore } from "react";

import {
  CalendarClock,
  Calculator,
  Compass,
  FileSearch,
  Mail,
  MapPinned,
  Plane,
  Sparkles,
} from "lucide-react";
import { TableIcon as Table2 } from "@/components/icons/product-icons";

import { useTranslations } from "next-intl";

import { STARTER_ICONS } from "@/lib/starter-icons";
import { Skeleton } from "@/components/ui/skeleton";
import { AgentAvatar } from "@/components/agents/agent-avatar";
import { useAgents, useAuth } from "@/hooks";
import { usePersonalStarterQuery } from "@/hooks/use-suggestions";
import { VISUALS_ID } from "@/lib/agent-spec";
import { useAgentSelectionStore } from "@/stores";
import type { Agent } from "@/types/agents";

import { ChatWelcome, WelcomeIcon, type WelcomeSuggestion } from "./chat-welcome";

/** The starter agent also offers personalized opening messages. */
const STARTER_SLUG = "agenticos";
const subscribeToClock = () => () => {};
const localHour = () => new Date().getHours();
const serverHour = () => null;

export function greetingKey(
  hour: number,
): "greetingNight" | "greetingMorning" | "greetingAfternoon" | "greetingEvening" {
  if (hour < 6) return "greetingNight";
  if (hour < 12) return "greetingMorning";
  if (hour < 18) return "greetingAfternoon";
  return "greetingEvening";
}

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
  suggestionsSlot?: HTMLElement | null;
}

export function ChatEmptyState({ onPick, suggestionsSlot }: ChatEmptyStateProps) {
  // Whoever will answer, so the page opens on them rather than on a generic
  // sparkle and a line about streaming and tool calls. The list is the one the
  // picker already holds.
  const selectedAgentId = useAgentSelectionStore((state) => state.selectedAgentId);
  const { agents, isLoading } = useAgents({ includeArchived: true });
  const agent = agents.find((candidate) => candidate.id === selectedAgentId);
  // The agent's own first messages, as its published version names them, in
  // the words its author wrote. The starter agent has none and offers the
  // person's own instead, written for them overnight in this organization
  // (#2301) - read only here, so no other agent's empty chat asks for them.
  const own = agent?.starters ?? [];
  const personal = usePersonalStarterQuery(agent?.slug === STARTER_SLUG && !own.length);
  const resolvingAgent =
    isLoading || (!agent && agents.some((candidate) => candidate.status === "published"));
  const waiting =
    resolvingAgent || (agent?.slug === STARTER_SLUG && !own.length && personal.isPending);
  return (
    <Welcome
      agent={agent}
      starters={own.length ? own : agent?.slug === STARTER_SLUG ? (personal.data ?? []) : []}
      loading={waiting}
      suggestionsSlot={suggestionsSlot}
      onPick={onPick}
    />
  );
}

interface WelcomeProps extends ChatEmptyStateProps {
  agent: Agent | undefined;
  /** First messages to offer, as written - the card is the message, so nothing under it. */
  starters: string[];
  loading?: boolean;
}

function Welcome({ agent, starters, loading, onPick, suggestionsSlot }: WelcomeProps) {
  const t = useTranslations("chat.empty");
  const th = useTranslations("workspaceHome");
  const { user } = useAuth();
  const hour = useSyncExternalStore(subscribeToClock, localHour, serverHour);
  const firstName = user?.full_name?.split(" ")[0] || user?.email?.split("@")[0];
  const description = agent?.description?.trim();
  // The published list already carries capabilities; no second request for home hints.
  const draws = agent?.published_capabilities?.includes(VISUALS_ID) === true;
  const isStarter = agent?.slug === STARTER_SLUG;
  // Without first messages, an agent that draws opens on what it can draw (#2302).
  const suggestions: WelcomeSuggestion[] = starters.length
    ? starters.slice(0, 4).map((starter, index) => ({
        key: `starter-${index}`,
        icon: STARTER_ICONS[agent?.starter_icons?.[starter] ?? "message"],
        title: agent?.starter_titles?.[starter]?.trim() || starter,
        prompt: starter,
        description: agent?.starter_titles?.[starter]?.trim() ? starter : "",
      }))
    : (draws ? VISUAL_PROMPTS : PROMPTS).map((p) => ({
        key: p.id,
        icon: p.icon,
        title: t(`${p.id}Title`),
        prompt: t(`${p.id}Prompt`),
      }));

  return (
    <ChatWelcome
      quiet
      loading={loading}
      suggestionsSlot={suggestionsSlot}
      mark={
        agent ? (
          <AgentAvatar
            agentId={agent.id}
            slug={agent.slug}
            hasAvatar={agent.has_avatar}
            colorSlot={agent.avatar_color}
            size="lg"
          />
        ) : loading ? (
          <Skeleton className="size-14 rounded-full" data-testid="welcome-agent-loading" />
        ) : (
          <WelcomeIcon icon={Sparkles} />
        )
      }
      title={
        hour === null
          ? ""
          : firstName
            ? t(greetingKey(hour), { name: firstName })
            : t("greetingAnonymous")
      }
      lead={
        isStarter ? (
          th("lead")
        ) : agent ? (
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
    />
  );
}
