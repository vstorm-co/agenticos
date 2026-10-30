"use client";

import { useState } from "react";
import { Bell, Pencil, Plus, Trash2 } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import { EmptyState, ErrorState } from "@/components/states";
import { Button, ConfirmDialog, ListCard, Switch } from "@/components/ui";
import { useWorkflowLogAlerts } from "@/hooks";
import { formatDateTimeSeconds } from "@/lib/utils";
import type { LogAlertRule } from "@/lib/workflows/types";

import { LogAlertDialog, type LogAlertChoices } from "./log-alert-dialog";

/**
 * The rules that tell people when a workflow's log crosses a threshold: each one's
 * condition in words, who it reaches, whether it is on and when it last fired.
 * Read by anyone who may see the workflow; changed only by someone who may edit it.
 */
export function LogAlerts({
  workflowId,
  canEdit,
  ...choices
}: { workflowId: string; canEdit: boolean } & LogAlertChoices) {
  const t = useTranslations("pages.workflows");
  const { rules, isLoading, error, refetch, update, remove, failed } =
    useWorkflowLogAlerts(workflowId);
  // `undefined` is closed, `null` is a new rule, a rule is that rule being changed.
  const [editing, setEditing] = useState<LogAlertRule | null | undefined>(undefined);
  const [deleting, setDeleting] = useState<LogAlertRule | null>(null);

  return (
    <>
      <ListCard
        title={t("alertsTitle")}
        counted={isLoading ? null : error !== null ? "" : t("alertsCount", { count: rules.length })}
        headerTour="workflow-log-alerts"
        controls={
          canEdit ? (
            <Button size="sm" onClick={() => setEditing(null)}>
              <Plus className="h-3.5 w-3.5" />
              {t("alertNew")}
            </Button>
          ) : undefined
        }
      >
        {error !== null ? (
          <ErrorState
            title={t("alertsFailed")}
            description={t("alertsFailedDetail")}
            cta={{ label: t("logsRetry"), onClick: () => void refetch() }}
          />
        ) : rules.length === 0 && !isLoading ? (
          <EmptyState
            icon={Bell}
            title={t("alertsEmpty")}
            description={canEdit ? t("alertsEmptyDetail") : t("alertsEmptyViewer")}
          />
        ) : (
          <ul className="divide-border divide-y">
            {rules.map((rule) => (
              <RuleRow
                key={rule.id}
                rule={rule}
                choices={choices}
                canEdit={canEdit}
                onToggle={(enabled) =>
                  update.mutate({ ruleId: rule.id, patch: { enabled } }, { onError: failed })
                }
                onEdit={() => setEditing(rule)}
                onDelete={() => setDeleting(rule)}
              />
            ))}
          </ul>
        )}
      </ListCard>
      {editing !== undefined && (
        <LogAlertDialog
          workflowId={workflowId}
          rule={editing}
          choices={choices}
          onClose={() => setEditing(undefined)}
        />
      )}
      {deleting !== null && (
        <ConfirmDialog
          open
          onOpenChange={() => setDeleting(null)}
          title={t("alertDeleteTitle")}
          description={t("alertDeleteDetail", { name: deleting.name })}
          confirmLabel={t("alertDelete")}
          destructive
          loading={remove.isPending}
          onConfirm={async () => {
            try {
              await remove.mutateAsync(deleting.id);
            } catch {
              // The hook has said why in a toast; the question has been answered.
            }
            setDeleting(null);
          }}
        />
      )}
    </>
  );
}

/**
 * The rule's outcomes the live version's step no longer logs. A rule is a server row
 * and is never rewritten here, only flagged - and only against the live version: with
 * none, or for a step it does not have, there is nothing to compare with.
 */
function outcomesGone(rule: LogAlertRule, livePorts: Map<string, string[]> | null): string[] {
  if (livePorts === null) return [];
  const live =
    rule.node_instance_id === null
      ? [...livePorts.values()].flat()
      : livePorts.get(rule.node_instance_id);
  if (live === undefined) return [];
  return rule.outcomes.filter((port) => !live.includes(port));
}

function RuleRow({
  rule,
  choices,
  canEdit,
  onToggle,
  onEdit,
  onDelete,
}: {
  rule: LogAlertRule;
  choices: LogAlertChoices;
  canEdit: boolean;
  onToggle: (enabled: boolean) => void;
  onEdit: () => void;
  onDelete: () => void;
}) {
  const t = useTranslations("pages.workflows");
  const locale = useLocale();
  const stepName =
    rule.node_instance_id === null
      ? null
      : (choices.steps.find(([id]) => id === rule.node_instance_id)?.[1] ?? rule.node_instance_id);
  const who = rule.audience
    .map((audience) =>
      audience === "chosen"
        ? t("alertPeopleChosen", { count: rule.user_ids.length })
        : t(audience === "admins" ? "alertAudienceAdmins" : "alertAudienceOwner"),
    )
    .join(", ");
  const gone = outcomesGone(rule, choices.livePorts);
  return (
    <li className="flex flex-wrap items-start gap-3 py-3">
      <div className="min-w-0 flex-1 space-y-0.5">
        <p className="text-sm font-medium">{rule.name}</p>
        <p className="text-muted-foreground text-xs">
          {t("alertCondition", {
            count: rule.threshold,
            outcomes: rule.outcomes.map((port) => choices.labels.get(port) ?? port).join(", "),
            hasStep: stepName === null ? "no" : "yes",
            step: stepName ?? "",
            hasText: rule.message_contains === null ? "no" : "yes",
            text: rule.message_contains ?? "",
            window: t(`alertWindows.${rule.window_minutes}`),
          })}
        </p>
        {gone.length > 0 && (
          <p className="text-destructive text-xs">
            {t("alertOutcomesGone", {
              outcomes: gone.map((port) => choices.labels.get(port) ?? port).join(", "),
            })}
          </p>
        )}
        <p className="text-muted-foreground text-xs">{t("alertTells", { who })}</p>
        <p className="text-muted-foreground text-xs">
          {rule.last_firing === null
            ? t("alertNeverFired")
            : t("alertLastFired", {
                when: formatDateTimeSeconds(rule.last_firing.fired_at, locale),
                count: rule.last_firing.count,
              })}
        </p>
      </div>
      <Switch
        checked={rule.enabled}
        disabled={!canEdit}
        aria-label={t("alertToggle", { name: rule.name })}
        onCheckedChange={onToggle}
      />
      {canEdit && (
        <div className="flex items-center gap-1">
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7"
            aria-label={t("alertEditNamed", { name: rule.name })}
            onClick={onEdit}
          >
            <Pencil className="h-3.5 w-3.5" />
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className="h-7 w-7"
            aria-label={t("alertDeleteNamed", { name: rule.name })}
            onClick={onDelete}
          >
            <Trash2 className="h-3.5 w-3.5" />
          </Button>
        </div>
      )}
    </li>
  );
}
