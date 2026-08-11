"use client";

import { useState } from "react";
import { Pause, Pencil, Play, Plus, Trash2, Zap } from "lucide-react";
import { useTranslations } from "next-intl";

import { TriggerFormDialog } from "@/components/triggers/trigger-form-dialog";
import { TriggerSummary } from "@/components/triggers/trigger-summary";
import { LoadingState } from "@/components/states";
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@/components/ui";
import { useTriggers } from "@/hooks/use-triggers";
import type { Trigger, TriggerType } from "@/types/triggers";

interface TriggersPanelProps {
  agentId: string;
  /**
   * Whether the caller may manage this agent's triggers. Managing one is the same
   * floor as running the agent (`agents:run`), which the server resolves per row;
   * the page passes the role-level answer in, and the server refuses anything a
   * grant does not actually widen.
   */
  canManage: boolean;
}

/**
 * When one agent runs itself - its schedules and event triggers, on the agent's
 * availability tab.
 *
 * The empty state says what the absence means: an agent with no triggers is not
 * misconfigured, it simply answers only when someone messages it, which is the
 * default. Every row action is hidden, not just disabled, for a caller who may
 * not manage them - the same rule the rest of the Builder follows.
 */
export function TriggersPanel({ agentId, canManage }: TriggersPanelProps) {
  const t = useTranslations("triggers");
  const { triggers, isLoading, setActive, runNow, remove } = useTriggers(agentId);
  const [creating, setCreating] = useState<TriggerType | null>(null);
  const [editing, setEditing] = useState<Trigger | null>(null);

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
          <div key={trigger.id} className="flex items-center gap-3 rounded-md border p-3">
            <div className="min-w-0 flex-1">
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
                <Button
                  variant="ghost"
                  size="sm"
                  aria-label={t("edit")}
                  onClick={() => setEditing(trigger)}
                >
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
          </div>
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
      {editing && (
        <TriggerFormDialog
          agentId={agentId}
          open
          trigger={editing}
          onOpenChange={(next) => !next && setEditing(null)}
        />
      )}
    </Card>
  );
}
