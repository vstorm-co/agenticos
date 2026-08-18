"use client";

import { useState } from "react";
import { Plus } from "lucide-react";
import { useTranslations } from "next-intl";

import { NewEventTriggerDialog } from "@/components/triggers/new-event-trigger-dialog";
import { TriggerFormDialog } from "@/components/triggers/trigger-form-dialog";
import { TriggerRow } from "@/components/triggers/trigger-row";
import { LoadingState } from "@/components/states";
import { Button, Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui";
import { useTriggers } from "@/hooks/use-triggers";

interface TriggersPanelProps {
  agentId: string;
  /**
   * Whether the caller may create a trigger on this agent - the role-level
   * `agents:run`, an agent-level signal that gates only the create buttons. Each
   * existing row decides its own controls from its `can_manage`, so this does not
   * reach them.
   */
  canManage: boolean;
}

/**
 * When one agent runs itself - its schedules and event triggers, on the agent's
 * availability tab.
 *
 * The empty state says what the absence means: an agent with no triggers is not
 * misconfigured, it simply answers only when someone messages it, which is the
 * default. The rows are the shared `TriggerRow`, so a pause here behaves exactly
 * as it does in the sidebar and the Activity tab; this panel adds only the
 * create buttons, which are hidden - not merely disabled - for a caller who may
 * not manage them. "New schedule" opens the cadence form; "New event trigger"
 * opens the portal grid, the default path to an event trigger.
 */
export function TriggersPanel({ agentId, canManage }: TriggersPanelProps) {
  const t = useTranslations("triggers");
  const { triggers, isLoading } = useTriggers(agentId);
  const [creatingSchedule, setCreatingSchedule] = useState(false);
  const [creatingEvent, setCreatingEvent] = useState(false);

  if (isLoading) return <LoadingState variant="skeleton-panel" rows={2} />;

  return (
    <Card>
      <CardHeader>
        <CardTitle>{t("panelTitle")}</CardTitle>
        <CardDescription>{t("panelDescription")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-3">
        {triggers.length === 0 && <p className="text-muted-foreground text-sm">{t("empty")}</p>}

        {triggers.map((trigger) => (
          <TriggerRow key={trigger.id} trigger={trigger} />
        ))}

        {canManage && (
          <div className="flex flex-wrap gap-2 border-t pt-3">
            <Button variant="outline" size="sm" onClick={() => setCreatingSchedule(true)}>
              <Plus className="mr-2 h-4 w-4" />
              {t("newSchedule")}
            </Button>
            <Button variant="outline" size="sm" onClick={() => setCreatingEvent(true)}>
              <Plus className="mr-2 h-4 w-4" />
              {t("newEvent")}
            </Button>
          </div>
        )}
      </CardContent>

      {creatingSchedule && (
        <TriggerFormDialog
          agentId={agentId}
          open
          initialType="schedule"
          onOpenChange={(next) => !next && setCreatingSchedule(false)}
        />
      )}

      {creatingEvent && (
        <NewEventTriggerDialog open onOpenChange={(next) => !next && setCreatingEvent(false)} />
      )}
    </Card>
  );
}
