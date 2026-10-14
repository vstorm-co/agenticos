"use client";

import { useTranslations } from "next-intl";
import { useState } from "react";

import { delegateNamed, type DelegateRef } from "@/lib/delegations";
import type { DelegationStatus, ToolCall } from "@/types";

import { DelegationHandoff, type HandoffLane } from "./delegation-handoff";
import { DelegationResult } from "./tool-results/delegation";

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
  const chosen = tasks.find((call) => call.id === opened);

  return (
    <section aria-label={t("teamOnThis")} className="max-w-xl">
      <p className="text-muted-foreground text-xs font-medium">
        {t("askedCount", { count: new Set(lanes.map((lane) => lane.delegate.slug)).size })}
      </p>
      <DelegationHandoff
        parent={parent}
        lanes={lanes}
        selected={opened}
        onSelect={(key) => setOpened(opened === key ? null : key)}
      />
      {chosen && (
        <DelegationResult
          brief={typeof chosen.args.description === "string" ? chosen.args.description : null}
          answer={typeof chosen.result === "string" ? chosen.result : ""}
        />
      )}
    </section>
  );
}
