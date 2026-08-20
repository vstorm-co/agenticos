"use client";

import { useState } from "react";
import { CalendarClock, Pause, Pencil, Play, Trash2, Zap } from "lucide-react";
import { useTranslations } from "next-intl";

import { AgentAvatar } from "@/components/agents/agent-avatar";
import { BrandIcon, isBrandName } from "@/components/icons/brand-icon";
import { EventSourceMark } from "@/components/triggers/event-source-mark";
import { TriggerFormDialog } from "@/components/triggers/trigger-form-dialog";
import { TriggerRunsSheet } from "@/components/triggers/trigger-runs-view";
import { TriggerSummary } from "@/components/triggers/trigger-summary";
import { Badge, Button, ConfirmDialog } from "@/components/ui";
import { useTriggers } from "@/hooks/use-triggers";
import type { Trigger } from "@/types/triggers";

/**
 * The mark every row leads with, so a mixed list stays aligned: a schedule gets
 * the clock, and an event trigger its provenance - a portal keeps its own brand
 * (Slack, Notion, whichever the preset is for), a raw trigger draws its event
 * source's mark from the shared lookup, so the row and the "Fires on" picker
 * never disagree.
 */
function TriggerMark({ trigger, className }: { trigger: Trigger; className?: string }) {
  if (trigger.trigger_type !== "event") {
    return <CalendarClock aria-hidden className={className} />;
  }
  if (trigger.portal_key && isBrandName(trigger.portal_key)) {
    return <BrandIcon name={trigger.portal_key} aria-hidden className={className} />;
  }
  if (trigger.event_source) {
    return <EventSourceMark source={trigger.event_source} className={className} />;
  }
  return <Zap aria-hidden className={className} />;
}

interface TriggerRowProps {
  trigger: Trigger;
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
 *
 * The controls gate on the row's own `can_manage`, resolved per trigger by the
 * server, so a Viewer holding an explicit run grant on one agent manages that
 * agent's triggers here without a role-level check hiding them first.
 */
export function TriggerRow({ trigger, showAgent = false }: TriggerRowProps) {
  const t = useTranslations("triggers");
  const { setActive, runNow, remove } = useTriggers(trigger.agent_id);
  const [editing, setEditing] = useState(false);
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [viewing, setViewing] = useState(false);
  // When "Run now" was pressed, so the runs view can show a waiting animation
  // until a reply recorded after this moment arrives. Null when the view was
  // opened just to read the log.
  const [pendingSince, setPendingSince] = useState<number | null>(null);

  function openRuns() {
    setPendingSince(null);
    setViewing(true);
  }

  function fireAndWatch() {
    // The boundary is the press, not the response: a fast fire can record its
    // reply before the 202 reaches the browser, and a boundary stamped after
    // that reply would wait forever for a message "newer" than it.
    const pressedAt = Date.now();
    runNow.mutate(trigger.id, {
      onSuccess: () => {
        setPendingSince(pressedAt);
        setViewing(true);
      },
    });
  }

  return (
    <div className="flex items-center gap-3 rounded-md border p-3">
      <button
        type="button"
        onClick={openRuns}
        aria-label={t("viewRuns")}
        className="hover:bg-muted/40 -m-1 flex min-w-0 flex-1 items-center gap-3 rounded p-1 text-left"
      >
        <TriggerMark trigger={trigger} className="text-muted-foreground h-5 w-5 shrink-0" />
        {showAgent && trigger.agent_name && (
          <AgentAvatar
            agentId={trigger.agent_id}
            name={trigger.agent_name}
            hasAvatar={trigger.agent_has_avatar ?? false}
            colorSlot={trigger.agent_avatar_color}
            size="sm"
            className="shrink-0"
          />
        )}
        <div className="min-w-0 flex-1">
          {(trigger.name || (showAgent && trigger.agent_name)) && (
            <p className="truncate text-xs font-medium">{trigger.name ?? trigger.agent_name}</p>
          )}
          {trigger.name && showAgent && trigger.agent_name && (
            <p className="text-muted-foreground truncate text-[11px]">{trigger.agent_name}</p>
          )}
          <p className="truncate text-sm">
            <TriggerSummary trigger={trigger} />
          </p>
          <p className="text-muted-foreground truncate text-xs">{trigger.prompt}</p>
        </div>
      </button>
      {!trigger.is_active && <Badge variant="secondary">{t("paused")}</Badge>}
      {trigger.can_manage && (
        <>
          <Button
            variant="ghost"
            size="sm"
            aria-label={t("runNow")}
            disabled={!trigger.is_active || runNow.isPending}
            onClick={fireAndWatch}
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
            onClick={() => setConfirmingDelete(true)}
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
      <ConfirmDialog
        open={confirmingDelete}
        onOpenChange={setConfirmingDelete}
        title={t("deleteTitle")}
        description={t("deleteConfirm")}
        confirmLabel={t("delete")}
        destructive
        onConfirm={() => remove.mutate(trigger.id)}
      />
      <TriggerRunsSheet
        trigger={trigger}
        pendingSince={pendingSince}
        open={viewing}
        onOpenChange={(next) => {
          setViewing(next);
          if (!next) setPendingSince(null);
        }}
      />
    </div>
  );
}
