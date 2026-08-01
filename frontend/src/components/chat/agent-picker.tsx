"use client";

import { useEffect } from "react";
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
          aria-label={`Agent: ${selected?.name ?? "none selected"}`}
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
            {selected?.name ?? "Choose agent"}
          </span>
          <ChevronDown className="text-foreground/45 h-3 w-3" />
        </button>
      </PopoverTrigger>

      <PopoverContent
        align="start"
        sideOffset={8}
        className="border-border bg-popover w-[320px] rounded-2xl border p-2 shadow-md"
      >
        <p className="text-foreground/55 px-2 pt-1 pb-2 text-xs leading-relaxed">
          {currentConversationId
            ? "Applies from your next message. Earlier answers keep the agent that gave them."
            : "Who answers this conversation."}
        </p>

        <div role="radiogroup" aria-label="Agent" className="space-y-1">
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
          <p className="text-foreground/55 px-2 py-3 text-xs">Loading…</p>
        ) : (
          runnable.length === 0 && (
            <p className="text-foreground/45 px-2 py-3 text-[11px] leading-relaxed">
              No published agents yet. Publish one from the Agents page and it will appear here.
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
  // The star sits beside the radio rather than inside it: a button cannot
  // contain a button, and starring an agent must not also select it.
  return (
    <div className="flex items-center gap-1">
      <button
        type="button"
        role="radio"
        aria-checked={selected}
        onClick={onSelect}
        className={cn(
          "flex min-w-0 flex-1 items-start gap-2.5 rounded-xl border px-2.5 py-2 text-left transition-all",
          selected
            ? "border-foreground/30 bg-accent text-foreground"
            : "border-border text-foreground/75 hover:border-foreground/25 hover:bg-accent/60 hover:text-foreground",
        )}
      >
        <AgentAvatar agentId={agent.id} name={agent.name} hasAvatar={agent.has_avatar} size="md" />
        <span className="min-w-0 flex-1">
          <span className="flex items-center gap-1.5 text-xs font-medium">
            <span className="truncate">{agent.name}</span>
            {isDefault && (
              <span className="text-foreground/55 shrink-0 font-mono text-[9px] tracking-wider uppercase">
                Default
              </span>
            )}
          </span>
          {agent.description && (
            <span className="text-foreground/55 mt-0.5 line-clamp-2 block text-[11px] leading-relaxed">
              {agent.description}
            </span>
          )}
        </span>
        {selected && <Check className="text-foreground mt-0.5 h-3.5 w-3.5 shrink-0" />}
      </button>
      <button
        type="button"
        aria-pressed={isDefault}
        aria-label={
          isDefault ? `Unset ${agent.name} as default agent` : `Set ${agent.name} as default agent`
        }
        title={isDefault ? "Default agent for new chats" : "Set as default for new chats"}
        onClick={onToggleDefault}
        className={cn(
          "shrink-0 rounded-lg p-1.5 transition-colors",
          isDefault
            ? "text-foreground"
            : "text-foreground/30 hover:text-foreground/70 hover:bg-accent/60",
        )}
      >
        <Star className={cn("h-3.5 w-3.5", isDefault && "fill-current")} />
      </button>
    </div>
  );
}
