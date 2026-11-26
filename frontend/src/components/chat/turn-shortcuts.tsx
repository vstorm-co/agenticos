"use client";

import { useState } from "react";
import { Bot, CalendarClock } from "lucide-react";
import { useTranslations } from "next-intl";

import { TriggerFormDialog } from "@/components/triggers/trigger-form-dialog";
import { useAssistant } from "@/hooks/use-assistant";
import { usePermissions } from "@/hooks/use-permissions";
import { cn } from "@/lib/utils";
import { useArchitectAskStore } from "@/stores/architect-ask-store";
import type { TriggerTemplate } from "@/types/trigger-templates";
import { Perm } from "@/types/permissions";

import { TURN_ACTION } from "./turn-action";

/** Weekly on Monday at 8:00 UTC - a cadence to change, not to keep. */
const WEEKLY = { schedule_kind: "cron", cron_expression: "0 8 * * 1" } as const;

interface TurnShortcutsProps {
  /** What the person asked, which the routine or the agent is made from. */
  request: string;
  /** The agent that answered it, which a routine runs by default. */
  agentId: string | null;
}

/**
 * Two ways to keep a request that worked (#2301): run it on a schedule, or hand
 * it to the Architect to make an agent of. Under the person's own message,
 * because that is the request - the answer is what it produced.
 */
export function TurnShortcuts({ request, agentId }: TurnShortcutsProps) {
  const t = useTranslations("chat.extras");
  const { can } = usePermissions();
  const { assistant } = useAssistant();
  const ask = useArchitectAskStore((state) => state.ask);
  const [scheduling, setScheduling] = useState(false);
  const template: TriggerTemplate = {
    key: "from-chat",
    label: t("routineFromChat"),
    description: "",
    prompt: request,
    trigger_type: "schedule",
    suggested_cadence: WEEKLY,
  };
  const architect = assistant?.status === "ready" && assistant.can_use;

  return (
    <>
      {can(Perm.agentsRun) && (
        <button
          type="button"
          onClick={() => setScheduling(true)}
          title={t("runOnSchedule")}
          aria-label={t("runOnSchedule")}
          className={cn(TURN_ACTION, "sm:opacity-0 sm:group-hover:opacity-100")}
        >
          <CalendarClock />
        </button>
      )}
      {architect && can(Perm.agentsEdit) && (
        <button
          type="button"
          onClick={() => ask(t("makeAgentAsk", { request }))}
          title={t("makeAgent")}
          aria-label={t("makeAgent")}
          className={cn(TURN_ACTION, "sm:opacity-0 sm:group-hover:opacity-100")}
        >
          <Bot />
        </button>
      )}
      {scheduling && (
        <TriggerFormDialog
          agentId={agentId}
          open={scheduling}
          onOpenChange={setScheduling}
          initialTemplate={template}
        />
      )}
    </>
  );
}
