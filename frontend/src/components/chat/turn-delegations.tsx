"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";

import { AgentAvatar } from "@/components/agents/agent-avatar";
import { Sheet, SheetClose, SheetContent } from "@/components/ui";
import { delegateNamed, type DelegateRef } from "@/lib/delegations";
import { cn } from "@/lib/utils";
import type { DelegationStatus, ToolCall } from "@/types";

import { DelegationHandoff, STATUS_KEY, type HandoffLane } from "./delegation-handoff";
import { MarkdownContent } from "./markdown-content";

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
 * Who worked on an answer, under it: the agent that was asked, and each agent it
 * handed part of the job to.
 *
 * The team is part of the answer, not only of the work above it - "Finance
 * Analyst and Support Desk did this" is what a reader wants at a glance, and the
 * folded steps hide it. Each delegate opens what it was asked and what it said,
 * the same two things its step holds.
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
  const [opened, setOpened] = useState<string | null>(null);
  const tasks = toolCalls.filter(
    (call) => call.name === "task" && typeof call.args.subagent_type === "string",
  );
  if (tasks.length === 0) return null;

  const lanes: HandoffLane[] = tasks.map((call) => ({
    key: call.id,
    delegate: delegateNamed(call.args.subagent_type as string, agents),
    status: statusOf(call),
  }));
  return (
    <section aria-label={t("teamOnThis")} className="max-w-xl">
      <p className="text-muted-foreground text-xs font-medium">
        {t("askedCount", { count: new Set(lanes.map((lane) => lane.delegate.slug)).size })}
      </p>
      <DelegationHandoff
        parent={parent}
        lanes={lanes}
        selected={opened}
        onSelect={(key) => setOpened(key)}
      />
      {opened !== null && (
        <DelegationSheet
          tasks={tasks}
          lanes={lanes}
          opened={opened}
          onOpen={setOpened}
          onClose={() => setOpened(null)}
        />
      )}
    </section>
  );
}

/**
 * One delegation, read at the side: who was asked, what they were asked, and what
 * they said - with the rest of the team along the top to move between them.
 *
 * At the side rather than under the answer, where a brief and a long reply
 * pushed the answer itself off the screen.
 */
function DelegationSheet({
  tasks,
  lanes,
  opened,
  onOpen,
  onClose,
}: {
  tasks: ToolCall[];
  lanes: HandoffLane[];
  opened: string;
  onOpen: (key: string) => void;
  onClose: () => void;
}) {
  const t = useTranslations("chat.delegation");
  const tTools = useTranslations("chat.tools");
  const index = tasks.findIndex((call) => call.id === opened);
  const call = tasks[index]!;
  const lane = lanes[index]!;
  const brief = typeof call.args.description === "string" ? call.args.description : null;
  const answer = typeof call.result === "string" ? call.result : "";

  return (
    <Sheet open onOpenChange={onClose}>
      <SheetContent side="right" className="bg-background w-full sm:max-w-lg">
        <div className="flex items-center gap-2 border-b px-4 py-3">
          {/* The team, to move between: each face is one delegation. */}
          <div role="tablist" aria-label={t("teamOnThis")} className="flex min-w-0 flex-1 gap-1">
            {lanes.map((each) => (
              <button
                key={each.key}
                type="button"
                role="tab"
                aria-selected={each.key === lane.key}
                title={each.delegate.name}
                aria-label={each.delegate.name}
                onClick={() => onOpen(each.key)}
                className={cn(
                  "rounded-full p-0.5 transition-opacity",
                  each.key === lane.key
                    ? "ring-foreground/30 ring-2"
                    : "opacity-55 hover:opacity-100",
                )}
              >
                <AgentAvatar
                  agentId={each.delegate.id ?? each.delegate.slug}
                  slug={each.delegate.slug}
                  hasAvatar={each.delegate.has_avatar}
                  colorSlot={each.delegate.avatar_color}
                  size="sm"
                  className="h-7 w-7"
                />
              </button>
            ))}
          </div>
          <SheetClose onClick={onClose} />
        </div>

        <div className="flex items-center gap-3 px-5 pt-5">
          <AgentAvatar
            agentId={lane.delegate.id ?? lane.delegate.slug}
            slug={lane.delegate.slug}
            hasAvatar={lane.delegate.has_avatar}
            colorSlot={lane.delegate.avatar_color}
            size="md"
            className="h-10 w-10"
          />
          <div className="min-w-0">
            <h2 className="text-foreground truncate text-base font-semibold">
              {lane.delegate.name}
            </h2>
            <p className="text-muted-foreground text-xs">{t(STATUS_KEY[lane.status])}</p>
          </div>
        </div>

        <div className="min-h-0 flex-1 scrollbar-thin space-y-5 overflow-y-auto px-5 py-5">
          {brief && (
            <section className="space-y-1.5">
              <h3 className="text-muted-foreground text-[11px] font-medium tracking-wide uppercase">
                {tTools("delegationBrief")}
              </h3>
              <p className="text-foreground/75 border-foreground/15 border-l-2 pl-3 text-[13px] leading-relaxed whitespace-pre-line">
                {brief}
              </p>
            </section>
          )}
          {answer && (
            <section className="space-y-1.5">
              <h3 className="text-muted-foreground text-[11px] font-medium tracking-wide uppercase">
                {tTools("delegationAnswer")}
              </h3>
              <div className="text-sm">
                <MarkdownContent content={answer} inertImages />
              </div>
            </section>
          )}
        </div>
      </SheetContent>
    </Sheet>
  );
}
