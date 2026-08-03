"use client";

import { useEffect } from "react";
import { useTranslations } from "next-intl";
import { Bot, Check, ChevronDown, Star } from "lucide-react";

import { AgentAvatar } from "@/components/agents/agent-avatar";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui";
import { useAgents } from "@/hooks";
import { useAgentSelectionStore, useConversationStore } from "@/stores";
import { cn } from "@/lib/utils";
import type { Agent } from "@/types/agents";

/**
 * Whether an agent can be chatted with at all.
 *
 * Only a published agent has a version to run - the backend refuses a draft or
 * an archived one - so offering it would turn the picker into a trap.
 */
export const isRunnable = (agent: Agent): boolean => agent.status === "published";

/**
 * Who answers, as its own control beside the composer.
 *
 * It was a tab inside a settings popover, which put the most consequential
 * choice in the conversation two clicks behind a slider. It is first-class
 * here, showing the agent's face, because "which of these five agents am I
 * talking to" is answered faster by a picture than by reading five names.
 *
 * Only the organization's published agents are offered - there is no general
 * assistant to fall back to. An empty or stale selection resolves to the
 * user's default agent - the one starred here - or, absent that, the first
 * published agent as soon as the list arrives, so the composer always
 * addresses someone real.
 *
 * The choice applies from the next message, not retroactively - switching
 * mid-conversation is a supported thing to do, and the transcript records the
 * agent and version per turn, so a thread that changed hands says so rather
 * than relabelling everything above it.
 */
export function AgentPicker() {
  const t = useTranslations("chat.agentPicker");
  // Archived agents included so a conversation that was had with one still
  // resolves its name; `isRunnable` is what decides who can be picked.
  const { agents, isLoading, isFetching } = useAgents({ includeArchived: true });
  const selectedAgentId = useAgentSelectionStore((state) => state.selectedAgentId);
  const selectAgent = useAgentSelectionStore((state) => state.select);
  const defaultAgentId = useAgentSelectionStore((state) => state.defaultAgentId);
  const setDefaultAgent = useAgentSelectionStore((state) => state.setDefault);
  const currentConversationId = useConversationStore((state) => state.currentConversationId);

  const runnable = agents.filter(isRunnable);
  const selected =
    agents.find((agent) => agent.id === selectedAgentId && isRunnable(agent)) ?? null;

  // No selection, or one pointing at an agent that has since been unpublished,
  // resolves to the default agent, then the first published one. The store is
  // read at send time, so this is also what keeps a frame from going out
  // without an agent.
  useEffect(() => {
    if (isLoading || selected !== null) return;
    // Not while the list is being refetched, and that is the whole of this
    // guard. React Query serves the previous answer until the new one lands, so
    // an agent published a second ago is missing from the list this render sees
    // - and falling back then does not fill in an empty choice, it *replaces* a
    // deliberate one. The Builder's "Open in chat" hands over an agent id and
    // navigates; the picker would quietly hand the conversation to somebody
    // else, having been told exactly who was wanted.
    if (isFetching && selectedAgentId !== null) return;
    const fallback = runnable.find((agent) => agent.id === defaultAgentId) ?? runnable[0];
    if (fallback) selectAgent(fallback.id);
  }, [isLoading, isFetching, selected, selectedAgentId, runnable, defaultAgentId, selectAgent]);

  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label={t("current", { name: selected?.name ?? t("noneSelected") })}
          className="border-foreground/10 bg-card hover:border-foreground/25 hover:bg-foreground/[0.04] text-foreground inline-flex items-center gap-1.5 rounded-full border py-1 pr-2 pl-1 transition-colors"
        >
          {selected ? (
            <AgentAvatar
              agentId={selected.id}
              name={selected.name}
              hasAvatar={selected.has_avatar}
              size="sm"
            />
          ) : (
            <span className="bg-foreground/8 flex h-6 w-6 items-center justify-center rounded-full">
              <Bot className="h-3 w-3" />
            </span>
          )}
          <span className="max-w-[160px] truncate font-mono text-[11px] tracking-wider uppercase">
            {selected?.name ?? t("none")}
          </span>
          <ChevronDown className="text-foreground/45 h-3 w-3" />
        </button>
      </PopoverTrigger>

      <PopoverContent
        align="start"
        sideOffset={8}
        className="border-border bg-popover w-[300px] rounded-xl border p-1.5 shadow-md"
      >
        {/* One line, and the smallest type in the menu. It is a footnote about when the
            change takes effect; at twelve pixels over two lines it was the loudest
            thing in a list of agents. */}
        <p className="text-muted-foreground border-foreground/8 mb-1 border-b px-2 pt-1 pb-2 text-[11px] leading-snug">
          {currentConversationId ? t("appliesNext") : t("whoAnswers")}
        </p>

        <div role="radiogroup" aria-label={t("label")} className="space-y-px">
          {runnable.map((agent) => (
            <AgentOption
              key={agent.id}
              agent={agent}
              selected={selectedAgentId === agent.id}
              isDefault={defaultAgentId === agent.id}
              onSelect={() => selectAgent(agent.id)}
              onToggleDefault={() => setDefaultAgent(defaultAgentId === agent.id ? null : agent.id)}
            />
          ))}
        </div>

        {isLoading && runnable.length === 0 ? (
          <p className="text-foreground/55 px-2 py-3 text-xs">{t("loading")}</p>
        ) : (
          runnable.length === 0 && (
            <p className="text-foreground/45 px-2 py-3 text-[11px] leading-relaxed">
              {t("nonePublished")}
            </p>
          )
        )}
      </PopoverContent>
    </Popover>
  );
}

function AgentOption({
  agent,
  selected,
  isDefault,
  onSelect,
  onToggleDefault,
}: {
  agent: Agent;
  selected: boolean;
  isDefault: boolean;
  onSelect: () => void;
  onToggleDefault: () => void;
}) {
  const t = useTranslations("chat.agentPicker");
  // Two buttons that read as one row: a button cannot contain a button, and starring an
  // agent must not also select it - so the *wrapper* carries the fill and the rounding,
  // and the star lives inside it rather than in an orphaned column beside it. What this
  // replaces gave every agent its own bordered card inside an already bordered popover,
  // which is four nested boxes to say "pick one of these".
  return (
    <div
      className={cn(
        "group flex items-center rounded-lg pr-1 transition-colors",
        selected ? "bg-accent" : "hover:bg-accent/60",
      )}
    >
      <button
        type="button"
        role="radio"
        aria-checked={selected}
        onClick={onSelect}
        className="flex min-w-0 flex-1 items-center gap-2.5 px-2 py-1.5 text-left"
      >
        <AgentAvatar agentId={agent.id} name={agent.name} hasAvatar={agent.has_avatar} size="sm" />
        <span className="min-w-0 flex-1">
          <span className="flex items-center gap-1.5">
            <span className="truncate text-[13px] font-medium">{agent.name}</span>
            {isDefault && (
              <span className="text-muted-foreground shrink-0 text-[10px]">{t("default")}</span>
            )}
          </span>
          {/* One line, truncated. Wrapped to two, a description made every row a
              different height and the list stopped scanning as a list. */}
          {agent.description && (
            <span className="text-muted-foreground block truncate text-[11px]">
              {agent.description}
            </span>
          )}
        </span>
        {selected && <Check className="text-foreground h-3.5 w-3.5 shrink-0" aria-hidden />}
      </button>
      <button
        type="button"
        aria-pressed={isDefault}
        aria-label={
          isDefault
            ? t("unsetDefault", { name: agent.name })
            : t("setDefault", { name: agent.name })
        }
        title={isDefault ? t("defaultForNewChats") : t("makeDefaultForNewChats")}
        onClick={onToggleDefault}
        className={cn(
          "shrink-0 rounded-md p-1.5 transition-colors",
          // Off-state stars on every row are four grey outlines competing with the
          // names; the one that is set is the only one worth showing unasked.
          isDefault
            ? "text-foreground"
            : "text-muted-foreground/50 hover:text-foreground opacity-0 group-hover:opacity-100 focus-visible:opacity-100",
        )}
      >
        <Star className={cn("h-3.5 w-3.5", isDefault && "fill-current")} />
      </button>
    </div>
  );
}
