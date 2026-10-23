"use client";

import {
  BookOpen,
  Calculator,
  FileSearch,
  Mail,
  MapPinned,
  Plane,
  Sparkles,
  Table2,
} from "lucide-react";

import { useTranslations } from "next-intl";

import { AgentAvatar } from "@/components/agents/agent-avatar";
import { useAgents, useAuth } from "@/hooks";
import { useMentionables } from "@/hooks/use-mentionables";
import { VISUALS_ID } from "@/lib/agent-spec";
import { useAgentSelectionStore } from "@/stores";

import { ChatWelcome, WelcomeIcon } from "./chat-welcome";

/** The four openers, in order. Their words live in the catalog under `empty.<id>*`. */
const PROMPTS = [
  { icon: FileSearch, id: "docs" },
  { icon: BookOpen, id: "concept" },
  { icon: Mail, id: "email" },
  { icon: Sparkles, id: "brainstorm" },
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
      suggestions={(draws ? VISUAL_PROMPTS : PROMPTS).map((p) => ({
        key: p.id,
        icon: p.icon,
        title: t(`${p.id}Title`),
        prompt: t(`${p.id}Prompt`),
      }))}
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
