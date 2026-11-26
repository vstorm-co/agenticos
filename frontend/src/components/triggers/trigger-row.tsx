"use client";

import { useState } from "react";
import { CalendarClock, Pause, Pencil, Play, ShieldCheck, Trash2, Zap } from "lucide-react";
import { useTranslations } from "next-intl";

import { AgentAvatar } from "@/components/agents/agent-avatar";
import { BrandIcon, isBrandName } from "@/components/icons/brand-icon";
import { EventSourceMark } from "@/components/triggers/event-source-mark";
import { RoutineAutoPause } from "@/components/triggers/failure-policy-field";
import { TriggerFormDialog } from "@/components/triggers/trigger-form-dialog";
import { TriggerRunsSheet } from "@/components/triggers/trigger-runs-view";
import { TriggerSummary } from "@/components/triggers/trigger-summary";
import { Badge, Button, ConfirmDialog, ActionTooltip, TooltipProvider } from "@/components/ui";
import { ActionConsentsDialog } from "@/components/triggers/action-consents-dialog";
import { RoutineBlockers } from "@/components/triggers/routine-blockers";
import { useAuthStore } from "@/stores";
import { useTriggers } from "@/hooks/use-triggers";
import { listedBlockers, stopsRunNow, type RoutineBlocker } from "@/lib/routine-readiness-api";
import { cn } from "@/lib/utils";
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
  /**
   * Why its next activation would not run, from the list's one readiness read
   * (`useRoutinesReadiness`). Without it, only what the listing itself proves.
   */
  blockers?: RoutineBlocker[];
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
export function TriggerRow({ trigger, showAgent = false, blockers: read }: TriggerRowProps) {
  const t = useTranslations("triggers");
  const me = useAuthStore((state) => state.user?.id);
  const [consenting, setConsenting] = useState(false);
  const { setActive, runNow, remove } = useTriggers(trigger.agent_id);
  const impersonating = useAuthStore((state) => Boolean(state.user?.impersonation));
  // Only its creator resumes a routine that acts as them - not an administrator acting as
  // the creator; anyone who manages it may pause it.
  const actsForSomeoneElse =
    trigger.runs_as_creator && (me !== trigger.created_by_user_id || impersonating);
  const [editing, setEditing] = useState(false);
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const [viewing, setViewing] = useState(false);
  const blockers = read ?? listedBlockers(trigger);
  const blocked = blockers.some((blocker) => blocker.severity === "blocked");
  const attention = blockers.some((blocker) => blocker.severity === "attention");
  const unknown = blockers.some((blocker) => blocker.severity === "unknown");
  const isOwner = me != null && me === trigger.created_by_user_id && !impersonating;
  // A parked previous run holds the schedule, not a manual run, so Run now stays.
  const runDisabled =
    !trigger.is_active ||
    blockers.some(stopsRunNow) ||
    runNow.isPending ||
    (trigger.waiting_device_count ?? 0) > 0;
  // Compare history identities rather than clocks from the browser and worker.
  const [activationId, setActivationId] = useState<string | null>(null);
  const [jobId, setJobId] = useState<string | null>(null);

  function openRuns() {
    setActivationId(null);
    setJobId(null);
    setViewing(true);
  }

  function fireAndWatch() {
    runNow.mutate(trigger.id, {
      onSuccess: (pending) => {
        setActivationId(pending.activation_id);
        setJobId(pending.job_id);
        setViewing(true);
      },
    });
  }

  return (
    // A chat result can be narrow on a wide screen: size the card by its own container.
    // Paused reads as greyed out whatever else is true; an active routine that will
    // not run is red, and one whose runs will stop on a person is amber.
    <article
      data-state={
        !trigger.is_active
          ? "paused"
          : blocked
            ? "blocked"
            : attention
              ? "attention"
              : unknown
                ? "unknown"
                : "ready"
      }
      className={cn(
        "@container/routine flex w-full min-w-0 flex-wrap items-center gap-3 rounded-xl border p-3 transition-colors",
        !trigger.is_active
          ? "border-foreground/8 bg-muted/40 hover:border-foreground/20"
          : blocked
            ? "border-destructive/40 bg-destructive/5 hover:border-destructive/60"
            : attention
              ? "border-warning/40 bg-warning/5 hover:border-warning/60"
              : "border-foreground/8 bg-card hover:border-foreground/20",
      )}
    >
      <button
        type="button"
        onClick={openRuns}
        aria-label={t("viewRuns")}
        className={cn(
          "hover:bg-muted/40 -m-1 flex w-full min-w-0 flex-1 basis-full items-center gap-3 rounded-lg p-1 text-left transition-colors @min-[48rem]/routine:basis-0",
          !trigger.is_active && "opacity-60 grayscale",
        )}
      >
        {/* The kind of routine in a tile, with the agent that runs it tucked into
            its corner - one mark to scan down the list rather than two loose icons. */}
        <span className="bg-muted relative flex h-10 w-10 shrink-0 items-center justify-center rounded-lg">
          <TriggerMark trigger={trigger} className="text-muted-foreground h-5 w-5" />
          {showAgent && trigger.agent_name && (
            <AgentAvatar
              agentId={trigger.agent_id}
              slug={trigger.agent_slug ?? ""}
              hasAvatar={trigger.agent_has_avatar ?? false}
              colorSlot={trigger.agent_avatar_color}
              size="sm"
              className="ring-card absolute -right-1.5 -bottom-1.5 h-5 w-5 ring-2"
            />
          )}
        </span>
        <div className="min-w-0 flex-1 space-y-0.5">
          {/* The routine's own name leads - it was the smallest text in the row,
              under the cadence it is only a property of. */}
          {(trigger.name || (showAgent && trigger.agent_name)) && (
            <p className="text-sm font-medium [overflow-wrap:anywhere]">
              {trigger.name ?? trigger.agent_name}
            </p>
          )}
          <p className="text-muted-foreground flex min-w-0 flex-wrap items-center gap-x-1.5 gap-y-0.5 text-xs">
            {trigger.name && showAgent && trigger.agent_name && (
              <>
                <span className="text-foreground/80 truncate">{trigger.agent_name}</span>
                <span aria-hidden>·</span>
              </>
            )}
            <span className="min-w-0 [overflow-wrap:anywhere]">
              <TriggerSummary trigger={trigger} />
            </span>
          </p>
          <p className="text-muted-foreground/80 line-clamp-2 text-xs [overflow-wrap:anywhere]">
            {trigger.prompt}
          </p>
        </div>
      </button>
      {trigger.last_delivery_status === "pending" && (
        <Badge variant="outline">{t("deliveryPending")}</Badge>
      )}
      {trigger.last_delivery_status === "unavailable" && (
        <Badge variant="secondary">{t("deliveryUnavailable")}</Badge>
      )}
      <div className="flex min-w-0 basis-full flex-wrap items-center gap-2 empty:hidden @min-[48rem]/routine:max-w-[50%] @min-[48rem]/routine:basis-auto">
        {trigger.runs_as_creator && <Badge variant="outline">{t("actsAsCreator")}</Badge>}
        {(trigger.waiting_device_count ?? 0) > 0 && (
          <Badge variant="secondary">
            {t("local.waitingDevice", { count: trigger.waiting_device_count ?? 0 })}
          </Badge>
        )}
        <RoutineAutoPause
          stoppedAt={trigger.auto_stopped_at}
          count={trigger.consecutive_failures}
        />
        {!trigger.is_active && !trigger.auto_stopped_at && !trigger.setup_required && (
          <Badge variant="secondary">{t("paused")}</Badge>
        )}
        {trigger.can_manage && (
          <TooltipProvider>
            <div className="ml-auto flex shrink-0 flex-wrap items-center gap-0.5">
              {isOwner && (
                <ActionTooltip label={t("toolSettings.title")}>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-8 w-8"
                    data-tour="routine-access"
                    aria-label={t("toolSettings.title")}
                    onClick={() => setConsenting(true)}
                  >
                    <ShieldCheck className="h-4 w-4" />
                  </Button>
                </ActionTooltip>
              )}
              <ActionTooltip label={t("runNow")} disabled={runDisabled}>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-8 w-8"
                  aria-label={t("runNow")}
                  disabled={runDisabled}
                  onClick={fireAndWatch}
                  data-tour="routine-run-now"
                >
                  <Zap className="h-4 w-4" />
                </Button>
              </ActionTooltip>
              <ActionTooltip label={t("edit")}>
                <Button
                  variant="ghost"
                  size="icon"
                  className="h-8 w-8"
                  aria-label={t("edit")}
                  onClick={() => setEditing(true)}
                >
                  <Pencil className="h-4 w-4" />
                </Button>
              </ActionTooltip>
              {(trigger.is_active || !actsForSomeoneElse) && (
                <ActionTooltip label={trigger.is_active ? t("pause") : t("resume")}>
                  <Button
                    variant="ghost"
                    size="icon"
                    className="h-8 w-8"
                    aria-label={trigger.is_active ? t("pause") : t("resume")}
                    disabled={setActive.isPending}
                    onClick={() => {
                      if (!trigger.is_active && trigger.setup_required) setConsenting(true);
                      else
                        setActive.mutate({ triggerId: trigger.id, isActive: !trigger.is_active });
                    }}
                  >
                    {trigger.is_active ? (
                      <Pause className="h-4 w-4" />
                    ) : (
                      <Play className="h-4 w-4" />
                    )}
                  </Button>
                </ActionTooltip>
              )}
              <ActionTooltip label={t("delete")}>
                <Button
                  variant="ghost"
                  size="icon"
                  className="hover:text-destructive h-8 w-8"
                  aria-label={t("delete")}
                  disabled={remove.isPending}
                  onClick={() => setConfirmingDelete(true)}
                >
                  <Trash2 className="h-4 w-4" />
                </Button>
              </ActionTooltip>
            </div>
          </TooltipProvider>
        )}
      </div>
      <RoutineBlockers
        blockers={blockers}
        paused={!trigger.is_active}
        canReview={isOwner}
        onReview={() => setConsenting(true)}
        onOpenRuns={openRuns}
      />
      {consenting && (
        <ActionConsentsDialog
          trigger={trigger}
          onClose={() => setConsenting(false)}
          onSaved={
            trigger.setup_required
              ? async () => {
                  await setActive.mutateAsync({ triggerId: trigger.id, isActive: true });
                }
              : undefined
          }
        />
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
        activationId={activationId}
        jobId={jobId}
        open={viewing}
        onOpenChange={(next) => {
          setViewing(next);
          if (!next) {
            setActivationId(null);
            setJobId(null);
          }
        }}
      />
    </article>
  );
}
