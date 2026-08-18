"use client";

import { useState } from "react";
import { Plus } from "lucide-react";
import { useTranslations } from "next-intl";

import { TriggerFormDialog } from "@/components/triggers/trigger-form-dialog";
import { TriggerRow } from "@/components/triggers/trigger-row";
import { LoadingState } from "@/components/states";
import { Button, Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui";
import { useTriggers } from "@/hooks/use-triggers";
import type { TriggerType } from "@/types/triggers";

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
 * not manage them.
 */
export function TriggersPanel({ agentId, canManage }: TriggersPanelProps) {
  const t = useTranslations("triggers");
  const { triggers, isLoading } = useTriggers(agentId);
  const [creating, setCreating] = useState<TriggerType | null>(null);

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
            <Button variant="outline" size="sm" onClick={() => setCreating("schedule")}>
              <Plus className="mr-2 h-4 w-4" />
              {t("newSchedule")}
            </Button>
            <Button variant="outline" size="sm" onClick={() => setCreating("event")}>
              <Plus className="mr-2 h-4 w-4" />
              {t("newTrigger")}
            </Button>
          </div>
        )}
      </CardContent>

      {creating && (
        <TriggerFormDialog
          agentId={agentId}
          open
          initialType={creating}
          onOpenChange={(next) => !next && setCreating(null)}
        />
      )}
    </Card>
  );
}
