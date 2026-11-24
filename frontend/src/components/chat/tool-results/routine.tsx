"use client";

import { toolLookupName } from "@/lib/tool-identity";

import { useFormatter, useTranslations } from "next-intl";

import { TriggerRow } from "@/components/triggers/trigger-row";
import { Button } from "@/components/ui/button";
import { useTriggers } from "@/hooks/use-triggers";
import type { ToolCall } from "@/types";

export interface RoutineReference {
  id: string;
  agentId: string;
}

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;

/** Only successful platform routine writes produce a management card. */
export function writtenRoutines(calls: readonly ToolCall[]): RoutineReference[] {
  const routines = new Map<string, RoutineReference>();
  for (const call of calls) {
    if (
      !["agenticos_create_routine", "agenticos_update_routine"].includes(toolLookupName(call)) ||
      call.status !== "completed"
    )
      continue;
    let value: unknown = call.result;
    if (typeof value === "string") {
      try {
        value = JSON.parse(value);
      } catch {
        continue;
      }
    }
    if (
      value !== null &&
      typeof value === "object" &&
      "id" in value &&
      typeof value.id === "string" &&
      UUID.test(value.id) &&
      "agent_id" in value &&
      typeof value.agent_id === "string" &&
      UUID.test(value.agent_id) &&
      "trigger_type" in value &&
      typeof value.trigger_type === "string" &&
      ["schedule", "event"].includes(value.trigger_type)
    ) {
      routines.set(value.id, { id: value.id, agentId: value.agent_id });
    }
  }
  return [...routines.values()];
}

/** Fetch current authorized state; a recorded tool result never grants management rights. */
export function RoutineResult({ routine }: { routine: RoutineReference }) {
  const t = useTranslations("triggers");
  const format = useFormatter();
  const { triggers, isLoading, error, refetch } = useTriggers(routine.agentId);
  if (isLoading)
    return (
      <p role="status" className="text-muted-foreground text-sm">
        {t("loadingRoutine")}
      </p>
    );
  if (error)
    return (
      <div role="alert" className="space-y-1 text-sm">
        <p>{t("routineLoadError")}</p>
        <Button variant="ghost" size="sm" onClick={() => void refetch()}>
          {t("retryRoutine")}
        </Button>
      </div>
    );
  const trigger = triggers.find((item) => item.id === routine.id);
  if (!trigger) return <p className="text-muted-foreground text-sm">{t("routineUnavailable")}</p>;
  return (
    <div className="space-y-1">
      <TriggerRow trigger={trigger} showAgent />
      {trigger.is_active && !trigger.paused_for_budget && trigger.next_fire_at && (
        <p className="text-muted-foreground text-xs">
          {t("nextActivation", {
            at: format.dateTime(new Date(trigger.next_fire_at), {
              dateStyle: "medium",
              timeStyle: "short",
            }),
          })}
        </p>
      )}
    </div>
  );
}
