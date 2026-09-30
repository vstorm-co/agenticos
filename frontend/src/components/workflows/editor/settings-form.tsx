"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import {
  Button,
  Input,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Switch,
} from "@/components/ui";
import { useWorkflows } from "@/hooks";
import { WORKFLOW_FAILED_TRIGGER } from "@/lib/workflows/triggers";
import type { WorkflowDetail, WorkflowSettings } from "@/lib/workflows/types";

const NONE = "none";

/** Every IANA timezone this browser knows, for the timezone field's suggestions. */
function timezones(): string[] {
  return Intl.supportedValuesOf("timeZone");
}

/** A whole number from a field, or null when it is empty. */
function wholeOrNull(text: string): number | null {
  const value = Number.parseInt(text, 10);
  return Number.isNaN(value) ? null : value;
}

/**
 * A workflow's settings: what it is run with rather than what it does, so they
 * are the workflow's and every later run takes them - the timezone its schedule
 * keeps, the deadline a run gets when nothing names one, the workflow started
 * when a run fails, and how long its runs are kept. **Save** writes them all.
 */
export function WorkflowSettingsForm({
  workflow,
  disabled,
  saving,
  onSave,
}: {
  workflow: WorkflowDetail;
  disabled: boolean;
  saving: boolean;
  onSave: (settings: WorkflowSettings) => void;
}) {
  const t = useTranslations("pages.workflows");
  const { workflows } = useWorkflows();
  const saved = workflow.settings;
  const [timezone, setTimezone] = useState(saved.timezone);
  const [deadline, setDeadline] = useState(
    saved.default_deadline_seconds === null ? "" : String(saved.default_deadline_seconds / 60),
  );
  const [errorWorkflow, setErrorWorkflow] = useState(saved.error_workflow_id ?? NONE);
  const [retention, setRetention] = useState(
    saved.run_retention_days === null ? "" : String(saved.run_retention_days),
  );
  const [keepSucceeded, setKeepSucceeded] = useState(saved.keep_succeeded_runs);
  const handlers = workflows.filter(
    (candidate) =>
      candidate.id !== workflow.id && candidate.live_trigger === WORKFLOW_FAILED_TRIGGER,
  );
  const minutes = wholeOrNull(deadline);

  const save = () =>
    onSave({
      timezone: timezone.trim() || "UTC",
      default_deadline_seconds: minutes === null ? null : minutes * 60,
      error_workflow_id: errorWorkflow === NONE ? null : errorWorkflow,
      run_retention_days: wholeOrNull(retention),
      keep_succeeded_runs: keepSucceeded,
    });

  return (
    <div className="space-y-6">
      <p className="text-muted-foreground text-sm">{t("settingsIntro")}</p>

      <div className="space-y-1.5">
        <Label htmlFor="workflow-timezone">{t("settingsTimezone")}</Label>
        <Input
          id="workflow-timezone"
          list="workflow-timezones"
          value={timezone}
          disabled={disabled}
          onChange={(event) => setTimezone(event.target.value)}
        />
        <datalist id="workflow-timezones">
          {timezones().map((zone) => (
            <option key={zone} value={zone} />
          ))}
        </datalist>
        <p className="text-muted-foreground text-xs">{t("settingsTimezoneHint")}</p>
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="workflow-deadline">{t("settingsDeadline")}</Label>
        <Input
          id="workflow-deadline"
          type="number"
          min={1}
          inputMode="numeric"
          placeholder={t("settingsDeadlineNone")}
          value={deadline}
          disabled={disabled}
          onChange={(event) => setDeadline(event.target.value)}
        />
        <p className="text-muted-foreground text-xs">{t("settingsDeadlineHint")}</p>
      </div>

      <div className="space-y-1.5">
        <Label>{t("settingsErrorWorkflow")}</Label>
        <Select value={errorWorkflow} onValueChange={setErrorWorkflow} disabled={disabled}>
          <SelectTrigger aria-label={t("settingsErrorWorkflow")}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={NONE}>{t("settingsErrorWorkflowNone")}</SelectItem>
            {handlers.map((candidate) => (
              <SelectItem key={candidate.id} value={candidate.id}>
                {candidate.name}
              </SelectItem>
            ))}
            {saved.error_workflow_id !== null &&
              !handlers.some((candidate) => candidate.id === saved.error_workflow_id) && (
                <SelectItem value={saved.error_workflow_id}>
                  {t("settingsErrorWorkflowGone")}
                </SelectItem>
              )}
          </SelectContent>
        </Select>
        <p className="text-muted-foreground text-xs">{t("settingsErrorWorkflowHint")}</p>
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="workflow-retention">{t("settingsRetention")}</Label>
        <Input
          id="workflow-retention"
          type="number"
          min={1}
          inputMode="numeric"
          placeholder={t("settingsRetentionForever")}
          value={retention}
          disabled={disabled}
          onChange={(event) => setRetention(event.target.value)}
        />
        <div className="flex items-center justify-between gap-3 pt-2">
          <Label htmlFor="workflow-keep-succeeded" className="font-normal">
            {t("settingsKeepSucceeded")}
          </Label>
          <Switch
            id="workflow-keep-succeeded"
            checked={keepSucceeded}
            disabled={disabled}
            onCheckedChange={setKeepSucceeded}
          />
        </div>
        <p className="text-muted-foreground text-xs">{t("settingsRetentionHint")}</p>
      </div>

      {!disabled && (
        <Button onClick={save} disabled={saving}>
          {t("settingsSave")}
        </Button>
      )}
    </div>
  );
}
