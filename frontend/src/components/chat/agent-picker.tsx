"use client";

import { Bot, Check, ChevronDown } from "lucide-react";

import { AgentAvatar } from "@/components/agents/agent-avatar";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui";
import { useAgents } from "@/hooks";
import { useAgentSelectionStore, useConversationStore } from "@/stores";
import { cn } from "@/lib/utils";
import type { Agent } from "@/types/agents";

/** What the general assistant is called wherever the agent choice is shown. */
export const GENERAL_ASSISTANT_LABEL = "General assistant";

/**
 * Whether an agent can be chatted with at all.
 *
 * Only a published agent has a version to run — the backend refuses a draft or
 * an archived one — so offering it would turn the picker into a trap.
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
 * The choice applies from the next message, not retroactively — switching
 * mid-conversation is a supported thing to do, and the transcript records the
 * agent and version per turn, so a thread that changed hands says so rather
 * than relabelling everything above it.
 */
export function AgentPicker() {
  // Archived agents included so a conversation that was had with one still
  // resolves its name; `isRunnable` is what decides who can be picked.
  const { agents, isLoading } = useAgents({ includeArchived: true });
  const selectedAgentId = useAgentSelectionStore((state) => state.selectedAgentId);
  const selectAgent = useAgentSelectionStore((state) => state.select);
  const currentConversationId = useConversationStore((state) => state.currentConversationId);

  const runnable = agents.filter(isRunnable);
  const selected =
    agents.find((agent) => agent.id === selectedAgentId && isRunnable(agent)) ?? null;

  return (
    <Popover>
      <PopoverTrigger asChild>
        <button
          type="button"
          aria-label={`Agent: ${selected?.name ?? GENERAL_ASSISTANT_LABEL}`}
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
            {selected?.name ?? GENERAL_ASSISTANT_LABEL}
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
          <AgentOption
            name={GENERAL_ASSISTANT_LABEL}
            description="The default assistant, on the model picked in controls."
            selected={selectedAgentId === null}
            onSelect={() => selectAgent(null)}
          />
          {runnable.map((agent) => (
            <AgentOption
              key={agent.id}
              agent={agent}
              name={agent.name}
              description={agent.description}
              selected={selectedAgentId === agent.id}
              onSelect={() => selectAgent(agent.id)}
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
  name,
  description,
  selected,
  onSelect,
}: {
  agent?: Agent;
  name: string;
  description?: string | null;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      role="radio"
      aria-checked={selected}
      onClick={onSelect}
      className={cn(
        "flex w-full items-start gap-2.5 rounded-xl border px-2.5 py-2 text-left transition-all",
        selected
          ? "border-foreground/30 bg-accent text-foreground"
          : "border-border text-foreground/75 hover:border-foreground/25 hover:bg-accent/60 hover:text-foreground",
      )}
    >
      {agent ? (
        <AgentAvatar agentId={agent.id} name={agent.name} hasAvatar={agent.has_avatar} size="md" />
      ) : (
        <span className="bg-foreground/8 flex h-9 w-9 shrink-0 items-center justify-center rounded-full">
          <Bot className="h-4 w-4" />
        </span>
      )}
      <span className="min-w-0 flex-1">
        <span className="block truncate text-xs font-medium">{name}</span>
        {description && (
          <span className="text-foreground/55 mt-0.5 line-clamp-2 block text-[11px] leading-relaxed">
            {description}
          </span>
        )}
      </span>
      {selected && <Check className="text-foreground mt-0.5 h-3.5 w-3.5 shrink-0" />}
    </button>
  );
}
