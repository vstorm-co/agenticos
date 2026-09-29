"use client";

import { useState } from "react";
import Link from "next/link";
import {
  ArrowUpCircle,
  CalendarClock,
  KeyRound,
  Pause,
  Pencil,
  Play,
  Trash2,
  Webhook,
} from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import { Badge, Button, ConfirmDialog } from "@/components/ui";
import { ROUTES } from "@/lib/constants";
import { scheduleText } from "@/lib/trigger-format";
import { cn, formatDateTime } from "@/lib/utils";
import type { WorkflowExposureRead } from "@/lib/workflows/types";

interface ExposureRowProps {
  exposure: WorkflowExposureRead;
  /** The workflow's live version, so a row pinned to an older one can offer to move. */
  currentVersionId: string | null;
  canEdit: boolean;
  busy?: boolean;
  onEdit: () => void;
  onSetActive: (active: boolean) => void;
  onRepin: () => void;
  onRotate: () => void;
  onDelete: () => void;
}

/**
 * One webhook or schedule: what fires it, which version it runs, when it next
 * does, and its controls.
 *
 * The version is on the row because an exposure is pinned: publishing again
 * leaves a running webhook on the version it was made against until someone
 * moves it, so a row behind the live version says so and offers the move.
 */
export function ExposureRow({
  exposure,
  currentVersionId,
  canEdit,
  busy,
  onEdit,
  onSetActive,
  onRepin,
  onRotate,
  onDelete,
}: ExposureRowProps) {
  const t = useTranslations("pages.workflows");
  const tTriggers = useTranslations("triggers");
  const locale = useLocale();
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const schedule = exposure.adapter === "schedule";
  const Icon = schedule ? CalendarClock : Webhook;
  const behind = currentVersionId !== null && exposure.workflow_version_id !== currentVersionId;
  const title =
    exposure.name ?? (schedule ? t("exposureDefaultSchedule") : t("exposureDefaultWebhook"));
  const summary = schedule
    ? scheduleText(
        {
          schedule_kind: exposure.schedule_kind ?? "interval",
          interval_seconds: exposure.interval_seconds,
          cron_expression: exposure.cron_expression,
        },
        tTriggers,
      )
    : t("exposureWebhookSummary");

  return (
    <li className={cn("rounded-lg border p-3", !exposure.is_active && "bg-muted/30")}>
      <div className="flex items-start gap-3">
        <span
          className={cn(
            "flex size-8 shrink-0 items-center justify-center rounded-lg",
            schedule
              ? "bg-amber-500/10 text-amber-700 dark:text-amber-300"
              : "bg-sky-500/10 text-sky-700 dark:text-sky-300",
          )}
        >
          <Icon aria-hidden="true" className="size-4" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-2">
            <p className="truncate text-sm font-medium">{title}</p>
            {!exposure.is_active && <Badge variant="secondary">{t("exposurePaused")}</Badge>}
          </div>
          <p className="text-muted-foreground truncate text-xs">{summary}</p>
          <div className="text-muted-foreground mt-1.5 flex flex-wrap items-center gap-x-3 gap-y-1 text-[0.6875rem]">
            <span>{t("exposureVersion", { version: exposure.version_number })}</span>
            {schedule && exposure.is_active && exposure.next_fire_at && (
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
        </div>
        {canEdit && (
          <div className="flex shrink-0 items-center">
            {schedule && (
              <Button
                variant="ghost"
                size="icon"
                aria-label={t("exposureEdit", { name: title })}
                disabled={busy}
                onClick={onEdit}
              >
                <Pencil className="h-4 w-4" />
              </Button>
            )}
            {!schedule && (
              <Button
                variant="ghost"
                size="icon"
                aria-label={t("exposureRotate", { name: title })}
                disabled={busy}
                onClick={onRotate}
              >
                <KeyRound className="h-4 w-4" />
              </Button>
            )}
            <Button
              variant="ghost"
              size="icon"
              aria-label={
                exposure.is_active
                  ? t("exposurePause", { name: title })
                  : t("exposureResume", { name: title })
              }
              disabled={busy}
              onClick={() => onSetActive(!exposure.is_active)}
            >
              {exposure.is_active ? <Pause className="h-4 w-4" /> : <Play className="h-4 w-4" />}
            </Button>
            <Button
              variant="ghost"
              size="icon"
              aria-label={t("exposureDelete", { name: title })}
              disabled={busy}
              onClick={() => setConfirmingDelete(true)}
            >
              <Trash2 className="h-4 w-4" />
            </Button>
          </div>
        )}
      </div>
      {behind && (
        <div className="mt-2 flex items-center justify-between gap-2 rounded-md bg-amber-500/10 px-2.5 py-1.5 text-xs text-amber-800 dark:text-amber-200">
          <span>{t("exposureBehind")}</span>
          {canEdit && (
            <Button size="sm" variant="ghost" className="h-7" disabled={busy} onClick={onRepin}>
              <ArrowUpCircle className="h-3.5 w-3.5" />
              {t("exposureRepin")}
            </Button>
          )}
        </div>
      )}
      <ConfirmDialog
        open={confirmingDelete}
        onOpenChange={setConfirmingDelete}
        title={t("exposureDeleteTitle")}
        description={
          schedule ? t("exposureDeleteScheduleConfirm") : t("exposureDeleteWebhookConfirm")
        }
        confirmLabel={t("exposureDeleteLabel")}
        destructive
        onConfirm={onDelete}
      />
    </li>
  );
}
