"use client";

import { useId, useState } from "react";
import { Command } from "cmdk";
import { Check, ChevronsUpDown } from "lucide-react";
import { useTranslations } from "next-intl";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui";
import { cn } from "@/lib/utils";
import type { Agent } from "@/types/agents";
import { AgentAvatar } from "./agent-avatar";

type AgentOption = Pick<
  Agent,
  "id" | "name" | "slug" | "description" | "has_avatar" | "avatar_color"
>;

/** The console's agent identity and searchable combobox treatment, without chat selection state. */
export function AgentSelect({
  agents,
  value,
  onChange,
  placeholder,
  loading,
  disabled,
  id,
  "aria-label": label,
  "aria-invalid": invalid,
  "aria-describedby": describedBy,
}: {
  agents: AgentOption[];
  value: string;
  onChange: (id: string) => void;
  placeholder: string;
  loading?: boolean;
  disabled?: boolean;
  id?: string;
  "aria-label"?: string;
  "aria-invalid"?: boolean;
  "aria-describedby"?: string;
}) {
  const t = useTranslations("agentSelect");
  const [open, setOpen] = useState(false);
  const listId = useId();
  const chosen = agents.find((agent) => agent.id === value);
  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <button
          id={id}
          type="button"
          role="combobox"
          aria-label={label}
          aria-expanded={open}
          aria-controls={listId}
          aria-invalid={invalid}
          aria-describedby={describedBy}
          disabled={disabled || loading}
          className="border-input bg-card focus-visible:ring-ring touch:min-h-11 aria-invalid:border-destructive flex min-h-9 w-full min-w-0 items-center gap-2 rounded-lg border px-3 py-1.5 text-left text-sm outline-none focus-visible:ring-2 disabled:opacity-50"
        >
          {chosen && (
            <AgentAvatar
              agentId={chosen.id}
              slug={chosen.slug}
              hasAvatar={chosen.has_avatar}
              colorSlot={chosen.avatar_color}
              size="sm"
            />
          )}
          <span className={cn("min-w-0 flex-1 truncate", !chosen && "text-muted-foreground")}>
            {chosen?.name ?? (loading ? t("loading") : placeholder)}
          </span>
          <ChevronsUpDown className="text-muted-foreground size-4 shrink-0" aria-hidden />
        </button>
      </PopoverTrigger>
      <PopoverContent
        align="start"
        className="w-[var(--radix-popover-trigger-width)] overflow-hidden p-0"
      >
        <Command>
          <Command.Input
            aria-label={t("search")}
            placeholder={t("search")}
            className="placeholder:text-muted-foreground h-11 w-full border-b bg-transparent px-3 text-sm outline-none"
          />
          <Command.List
            id={listId}
            className="max-h-[min(16rem,calc(var(--radix-popover-content-available-height)-3rem))] scrollbar-thin overflow-y-auto overscroll-contain p-1"
          >
            <Command.Empty className="text-muted-foreground px-3 py-5 text-center text-sm">
              {t("empty")}
            </Command.Empty>
            {agents.map((agent) => (
              <Command.Item
                key={agent.id}
                value={agent.id}
                keywords={[agent.name, agent.slug]}
                onSelect={() => {
                  onChange(agent.id);
                  setOpen(false);
                }}
                className="data-[selected=true]:bg-accent touch:min-h-11 flex cursor-pointer items-center gap-2.5 rounded-lg px-2 py-2 text-sm"
              >
                <AgentAvatar
                  agentId={agent.id}
                  slug={agent.slug}
                  hasAvatar={agent.has_avatar}
                  colorSlot={agent.avatar_color}
                  size="sm"
                />
                <span className="min-w-0 flex-1">
                  <span className="block truncate font-medium">{agent.name}</span>
                  {agent.description && (
                    <span className="text-muted-foreground block truncate text-xs">
                      {agent.description}
                    </span>
                  )}
                </span>
                {value === agent.id && <Check className="size-4 shrink-0" aria-hidden />}
              </Command.Item>
            ))}
          </Command.List>
        </Command>
      </PopoverContent>
    </Popover>
  );
}
