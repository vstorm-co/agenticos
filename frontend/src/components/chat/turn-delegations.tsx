"use client";

import { Check, ChevronRight } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { useState } from "react";

import { AgentAvatar } from "@/components/agents/agent-avatar";
import { delegateNamed, taskOutcome, type DelegateRef } from "@/lib/delegations";
import { cn } from "@/lib/utils";
import type { DelegationStatus, ToolCall } from "@/types";

import { DelegationSheet, type SheetDelegation } from "./delegation-sheet";

/** Where a `task` call's work stands, in the words a delegation uses. */
function statusOf(call: ToolCall): DelegationStatus {
  switch (call.status) {
    case "completed":
      return "completed";
    case "error":
      return "failed";
    case "awaiting_approval":
      return "awaiting_approval";
    case "unfinished":
      return "cancelled";
    default:
      return "running";
  }
}

/**
 * Who an answer was talked through with, as one line under it: the faces of the
 * agent and of each colleague it asked, and how many exchanges it took.
 *
 * One line because the answer is the point and the team is its byline. Each
 * colleague appears once however often it was asked; the line opens every
 * exchange - brief and answer - at the side.
 */
export function TurnDelegations({
  toolCalls,
  parent,
  agents,
}: {
  toolCalls: ToolCall[];
  parent?: DelegateRef;
  agents: readonly DelegateRef[];
}) {
  const t = useTranslations("chat.delegation");
  const locale = useLocale();
  const [opened, setOpened] = useState<string | null>(null);
  const tasks = toolCalls.filter(
    (call) => call.name === "task" && typeof call.args.subagent_type === "string",
  );
  if (tasks.length === 0) return null;

  const items: SheetDelegation[] = tasks.map((call) => {
    // A background start answers with its handle; what it came to is read from
    // the check of its task later in the turn, or it is still working.
    const background = taskOutcome(call, toolCalls);
    return {
      key: call.id,
      delegate: delegateNamed(call.args.subagent_type as string, agents),
      status: background?.status ?? statusOf(call),
      brief: typeof call.args.description === "string" ? call.args.description : null,
      answer: background?.answer ?? (typeof call.result === "string" ? call.result : ""),
    };
  });
  const team = [...new Map(items.map((item) => [item.delegate.slug, item])).values()];
  const names = new Intl.ListFormat(locale, { type: "conjunction" }).format(
    team.map((item) => item.delegate.name),
  );

  return (
    <>
      <button
        type="button"
        onClick={() => setOpened(items[0]!.key)}
        aria-label={t("openExchanges")}
        className="group/team text-muted-foreground hover:text-foreground flex max-w-full items-center gap-2 text-xs transition-colors"
      >
        <span className="flex shrink-0">
          {parent && (
            <AgentAvatar
              agentId={parent.id ?? parent.slug}
              slug={parent.slug}
              hasAvatar={parent.has_avatar}
              colorSlot={parent.avatar_color}
              size="sm"
              className="ring-background h-5 w-5 ring-2"
            />
          )}
          {team.map((item, index) => (
            <span
              key={item.delegate.slug}
              className={cn("relative", (parent !== undefined || index > 0) && "-ml-1.5")}
            >
              <AgentAvatar
                agentId={item.delegate.id ?? item.delegate.slug}
                slug={item.delegate.slug}
                hasAvatar={item.delegate.has_avatar}
                colorSlot={item.delegate.avatar_color}
                size="sm"
                className="ring-background h-5 w-5 ring-2"
              />
              {item.status === "completed" && (
                <span className="bg-success ring-background absolute -right-0.5 -bottom-0.5 grid size-2.5 place-items-center rounded-full ring-2">
                  <Check className="text-background h-1.5 w-1.5" strokeWidth={4} aria-hidden />
                </span>
              )}
            </span>
          ))}
        </span>
        <span className="min-w-0 truncate">
          {t("talkedWith", { names })} · {t("exchangeCount", { count: items.length })}
        </span>
        <ChevronRight className="h-3.5 w-3.5 shrink-0" aria-hidden />
      </button>
      {opened !== null && (
        <DelegationSheet
          items={items}
          opened={opened}
          onOpen={setOpened}
          onClose={() => setOpened(null)}
        />
      )}
    </>
  );
}
