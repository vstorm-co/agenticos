"use client";

import { useState } from "react";
import { Pause, Pencil, Play, Trash2, Zap } from "lucide-react";
import { useTranslations } from "next-intl";

import { TriggerFormDialog } from "@/components/triggers/trigger-form-dialog";
import { TriggerSummary } from "@/components/triggers/trigger-summary";
import { Badge, Button } from "@/components/ui";
import { useTriggers } from "@/hooks/use-triggers";
import type { Trigger } from "@/types/triggers";

interface TriggerRowProps {
  trigger: Trigger;
  /** Whether the caller may manage triggers - role-level `agents:run`. */
  canManage: boolean;
  /**
   * Whether to name the agent this trigger belongs to. The org-wide surfaces show
   * a trigger away from its agent's page and need to name it; the agent's own
   * panel does not, because the agent is the page.
   */
  showAgent?: boolean;
}

/**
 * One trigger, with its actions, wherever a list of them is shown.
 *
 * Its own `useTriggers` keyed on the trigger's agent, so a list spanning many
 * agents can act on each row - a single hook would only reach one agent's writes.
 * The row is the shared shape behind the Activity tab and the sidebar section, so
 * a pause looks and behaves the same in both.
 */
export function TriggerRow({ trigger, canManage, showAgent = false }: TriggerRowProps) {
  const t = useTranslations("triggers");
  const { setActive, runNow, remove } = useTriggers(trigger.agent_id);
  const [editing, setEditing] = useState(false);

  return (
    <div className="flex items-center gap-3 rounded-md border p-3">
      <div className="min-w-0 flex-1">
        {showAgent && trigger.agent_name && (
          <p className="truncate text-xs font-medium">{trigger.agent_name}</p>
        )}
        <p className="truncate text-sm">
          <TriggerSummary trigger={trigger} />
        </p>
        <p className="text-muted-foreground truncate text-xs">{trigger.prompt}</p>
      </div>
      {!trigger.is_active && <Badge variant="secondary">{t("paused")}</Badge>}
      {canManage && (
        <>
          <Button
            variant="ghost"
            size="sm"
            aria-label={t("runNow")}
            disabled={!trigger.is_active || runNow.isPending}
            onClick={() => runNow.mutate(trigger.id)}
          >
            <Zap className="h-4 w-4" />
          </Button>
          <Button variant="ghost" size="sm" aria-label={t("edit")} onClick={() => setEditing(true)}>
            <Pencil className="h-4 w-4" />
          </Button>
          <Button
            variant="ghost"
            size="sm"
            aria-label={trigger.is_active ? t("pause") : t("resume")}
            disabled={setActive.isPending}
            onClick={() =>
              setActive.mutate({ triggerId: trigger.id, isActive: !trigger.is_active })
            }
          >
            {trigger.is_active ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
          </Button>
          <Button
            variant="ghost"
            size="sm"
            aria-label={t("delete")}
            disabled={remove.isPending}
            onClick={() => remove.mutate(trigger.id)}
          >
            <Trash2 className="h-4 w-4" />
          </Button>
        </>
      )}
      {editing && (
        <TriggerFormDialog
          agentId={trigger.agent_id}
          open
          trigger={trigger}
          onOpenChange={(next) => !next && setEditing(false)}
        />
      )}
    </div>
  );
}
