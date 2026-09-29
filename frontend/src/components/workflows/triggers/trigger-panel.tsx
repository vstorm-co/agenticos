"use client";

import { useState } from "react";
import Link from "next/link";
import { KeyRound, Pause, Play } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import { LoadingState } from "@/components/states";
import { Badge, Button } from "@/components/ui";
import { nodeVisual } from "@/components/workflows/node-visuals";
import { usePublicConfig } from "@/components/public-config/public-config-provider";
import { useWorkflowExposure } from "@/hooks";
import { ROUTES } from "@/lib/constants";
import { scheduleText } from "@/lib/trigger-format";
import { cn, formatDateTime } from "@/lib/utils";
import {
  CHAT_TRIGGER,
  API_TRIGGER,
  MANUAL_TRIGGER,
  SCHEDULE_TRIGGER,
  TABLE_RECORD_TRIGGER,
  WEBHOOK_TRIGGER,
  isTrigger,
} from "@/lib/workflows/triggers";
import type {
  NodeDefinition,
  WorkflowDetail,
  WorkflowExposureRead,
  WorkflowExposureWithSecret,
  WorkflowGraph,
} from "@/lib/workflows/types";

import { CopyableValue } from "./copyable-value";
import { WebhookSecretDialog } from "./webhook-secret-dialog";

interface TriggerPanelProps {
  workflow: WorkflowDetail;
  /** The draft being edited, to say when it starts differently from the live version. */
  draft: WorkflowGraph | null;
  catalog: NodeDefinition[];
  canEdit: boolean;
}

/**
 * How this workflow starts, in the editor's Trigger sheet.
 *
 * The trigger is a node on the canvas and publishing switches it on, so this is
 * an overview rather than a form: which trigger the live version starts from,
 * whether the draft would change it, and the live state of the one that runs
 * unattended - a webhook's address and secret, a schedule's next tick, pausing.
 */
export function TriggerPanel({ workflow, draft, catalog, canEdit }: TriggerPanelProps) {
  const t = useTranslations("pages.workflows");
  const byId = new Map(catalog.map((definition) => [definition.id, definition]));
  const live = workflow.current_version_id === null ? undefined : workflow.live_trigger;
  const draftTrigger = draft?.nodes.find((node) => isTrigger(byId.get(node.definition_id) ?? null));
  const nameOf = (id: string | null) =>
    id === null ? t("triggerNone") : (byId.get(id)?.name ?? id);

  return (
    <div className="space-y-6">
      {live === undefined ? (
        <p className="text-muted-foreground rounded-lg border border-dashed p-4 text-center text-sm">
          {t("triggerNeedsPublish")}
        </p>
      ) : (
        <LiveTrigger
          workflow={workflow}
          trigger={live}
          name={nameOf(live)}
          definition={live === null ? undefined : byId.get(live)}
          draftConfig={draftTrigger?.definition_id === live ? draftTrigger.config : undefined}
          canEdit={canEdit}
        />
      )}
      {draft !== null && (draftTrigger?.definition_id ?? null) !== (live ?? null) && (
        <p className="rounded-lg border px-3 py-2 text-xs">
          {t("triggerDraftDiffers", {
            draft: nameOf(draftTrigger?.definition_id ?? null),
          })}
        </p>
      )}
    </div>
  );
}

interface LiveTriggerProps {
  workflow: WorkflowDetail;
  trigger: string | null;
  name: string;
  definition: NodeDefinition | undefined;
  /** The draft's configuration of the same trigger, where it names a table. */
  draftConfig: Record<string, unknown> | undefined;
  canEdit: boolean;
}

function LiveTrigger({
  workflow,
  trigger,
  name,
  definition,
  draftConfig,
  canEdit,
}: LiveTriggerProps) {
  const t = useTranslations("pages.workflows");
  const { apiUrl } = usePublicConfig();
  const visual = nodeVisual(trigger ?? API_TRIGGER, definition?.category ?? "");
  const Icon = visual.icon;
  const table = draftConfig?.["table"];
  const tableId =
    table !== null && typeof table === "object" && "table_id" in table
      ? String(table.table_id)
      : null;

  return (
    <section className="space-y-4">
      <div className="flex items-start gap-3">
        <span
          className={cn(
            "flex size-8 shrink-0 items-center justify-center rounded-lg",
            visual.tileClass,
          )}
        >
          <Icon aria-hidden="true" className="size-4" />
        </span>
        <div className="min-w-0">
          <p className="text-muted-foreground text-xs">{t("triggerLive")}</p>
          <h3 className="text-sm font-medium">{name}</h3>
        </div>
      </div>
      {trigger === MANUAL_TRIGGER && (
        <p className="text-muted-foreground text-xs">{t("exposureManualDescription")}</p>
      )}
      {(trigger === null || trigger === API_TRIGGER) && (
        <div className="space-y-3">
          <p className="text-muted-foreground text-xs">{t("exposureCallDescription")}</p>
          <CopyableValue
            id="workflow-api-url"
            label={t("exposureApiLabel")}
            value={`POST ${apiUrl}/api/v1/workflow-runs`}
          />
          <CopyableValue
            id="workflow-api-body"
            label={t("exposureApiBody")}
            value={JSON.stringify({ workflow_id: workflow.id, input: {} })}
          />
          <p className="text-muted-foreground text-xs">{t("exposureSocketNote")}</p>
        </div>
      )}
      {trigger === CHAT_TRIGGER && (
        <p className="text-muted-foreground text-xs">{t("triggerChatLive")}</p>
      )}
      {(trigger === WEBHOOK_TRIGGER || trigger === SCHEDULE_TRIGGER) && (
        <ExposureStatus workflow={workflow} canEdit={canEdit} />
      )}
      {trigger === TABLE_RECORD_TRIGGER && (
        <div className="space-y-2">
          <p className="text-muted-foreground text-xs">{t("triggerTableLive")}</p>
          {tableId !== null && (
            <Button variant="outline" size="sm" asChild>
              <Link href={ROUTES.TABLE_DETAIL(tableId)}>{t("triggerOpenTable")}</Link>
            </Button>
          )}
        </div>
      )}
    </section>
  );
}

/** A live webhook or schedule: its address or cadence, its state, and pausing it. */
function ExposureStatus({ workflow, canEdit }: { workflow: WorkflowDetail; canEdit: boolean }) {
  const t = useTranslations("pages.workflows");
  const tTriggers = useTranslations("triggers");
  const locale = useLocale();
  const { exposure, isLoading, setActive, rotate } = useWorkflowExposure(workflow.id);
  const [revealed, setRevealed] = useState<WorkflowExposureWithSecret | null>(null);

  if (isLoading) return <LoadingState variant="skeleton-panel" rows={2} />;
  if (exposure === null) return null;
  const busy = setActive.isPending || rotate.isPending;

  return (
    <div className={cn("space-y-3 rounded-lg border p-3", !exposure.is_active && "bg-muted/30")}>
      <div className="flex items-center justify-between gap-2">
        <div className="flex min-w-0 items-center gap-2">
          <Badge variant={exposure.is_active ? "outline" : "secondary"}>
            {exposure.is_active ? t("triggerOn") : t("exposurePaused")}
          </Badge>
          <span className="text-muted-foreground truncate text-xs">
            {t("exposureVersion", { version: exposure.version_number })}
          </span>
        </div>
        {canEdit && (
          <div className="flex shrink-0 items-center gap-1">
            {exposure.adapter === "webhook" && (
              <Button
                variant="ghost"
                size="sm"
                disabled={busy}
                onClick={() => rotate.mutate(exposure.id, { onSuccess: setRevealed })}
              >
                <KeyRound className="h-4 w-4" />
                {t("triggerRotate")}
              </Button>
            )}
            <Button
              variant="ghost"
              size="sm"
              disabled={busy}
              onClick={() => setActive.mutate({ id: exposure.id, active: !exposure.is_active })}
            >
              {exposure.is_active ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
              {exposure.is_active ? t("triggerPause") : t("triggerResume")}
            </Button>
          </div>
        )}
      </div>
      {exposure.webhook_url !== null && (
        <CopyableValue id="webhook-url" label={t("webhookUrl")} value={exposure.webhook_url} />
      )}
      {exposure.adapter === "schedule" && (
        <p className="text-sm">{scheduleText(cadenceOf(exposure), tTriggers)}</p>
      )}
      <div className="text-muted-foreground flex flex-wrap gap-x-3 gap-y-1 text-xs">
        {exposure.adapter === "schedule" && exposure.is_active && exposure.next_fire_at && (
          <span>
            {t("exposureNextFire", { when: formatDateTime(exposure.next_fire_at, locale) })}
          </span>
        )}
        {exposure.last_run_id && (
          <Link
            href={ROUTES.WORKFLOW_RUN_DETAIL(exposure.workflow_id, exposure.last_run_id)}
            className="hover:text-foreground underline-offset-2 hover:underline"
          >
            {t("exposureLastRun")}
          </Link>
        )}
      </div>
      {revealed?.webhook_url && (
        <WebhookSecretDialog
          url={revealed.webhook_url}
          secret={revealed.reveal_secret}
          onClose={() => setRevealed(null)}
        />
      )}
    </div>
  );
}

function cadenceOf(exposure: WorkflowExposureRead) {
  return {
    schedule_kind: exposure.schedule_kind ?? "interval",
    interval_seconds: exposure.interval_seconds,
    cron_expression: exposure.cron_expression,
  };
}
