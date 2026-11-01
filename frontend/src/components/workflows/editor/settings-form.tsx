"use client";

import { useState } from "react";
import { useLocale, useTranslations } from "next-intl";

import {
  Button,
  Input,
  Label,
  MoreOptions,
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

/**
 * The time it is now in a timezone, or null when the browser does not know the
 * zone - the field then says so rather than letting a schedule run in a place
 * that does not exist.
 */
function timeIn(zone: string, locale: string): string | null {
  try {
    return new Intl.DateTimeFormat(locale, {
      timeZone: zone,
      hour: "2-digit",
      minute: "2-digit",
    }).format(new Date());
  } catch (error) {
    if (error instanceof RangeError) return null;
    throw error;
  }
}

/** Native number inputs validate before submit; an empty field means no limit. */
function numberOrNull(text: string): number | null {
  return text.trim() === "" ? null : Number(text);
}

/** A setting as its field shows it: empty for none. */
function shown(value: number | null): string {
  return value === null ? "" : String(value);
}

/**
 * A workflow's settings: what it is run with rather than what it does, so they
 * are the workflow's and every later run takes them - the timezone its schedule
 * keeps, the deadline a run gets when nothing names one, the workflow started
 * when a run fails, how long its runs are kept, and what it may run and spend
 * at once and in a month. **Save** writes them all.
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
  const locale = useLocale();
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
  const [concurrent, setConcurrent] = useState(shown(saved.max_concurrent_runs));
  const [runBudget, setRunBudget] = useState(shown(saved.run_budget_usd));
  const [monthlyBudget, setMonthlyBudget] = useState(shown(saved.monthly_budget_usd));
  const handlers = workflows.filter(
    (candidate) =>
      candidate.id !== workflow.id &&
      (candidate.live_triggers?.length
        ? candidate.live_triggers
        : [candidate.live_trigger]
      ).includes(WORKFLOW_FAILED_TRIGGER),
  );
  const minutes = numberOrNull(deadline);
  const zone = timezone.trim() || "UTC";
  const now = timeIn(zone, locale);

  const save = () =>
    onSave({
      timezone: zone,
      default_deadline_seconds: minutes === null ? null : Math.round(minutes * 60),
      error_workflow_id: errorWorkflow === NONE ? null : errorWorkflow,
      run_retention_days: numberOrNull(retention),
      keep_succeeded_runs: keepSucceeded,
      max_concurrent_runs: numberOrNull(concurrent),
      run_budget_usd: numberOrNull(runBudget),
      monthly_budget_usd: numberOrNull(monthlyBudget),
    });

  return (
    <form
      className="space-y-6"
      onSubmit={(event) => {
        event.preventDefault();
        if (!disabled && !saving && now !== null) save();
      }}
    >
      <p className="text-muted-foreground text-sm">{t("settingsIntro")}</p>

      <div className="space-y-1.5">
        <Label htmlFor="workflow-timezone">{t("settingsTimezone")}</Label>
        <Input
          id="workflow-timezone"
          list="workflow-timezones"
          value={timezone}
          disabled={disabled}
          aria-invalid={now === null}
          aria-describedby="workflow-timezone-hint"
          onChange={(event) => setTimezone(event.target.value)}
        />
        <datalist id="workflow-timezones">
          {timezones().map((zone) => (
            <option key={zone} value={zone} />
          ))}
        </datalist>
        {now === null ? (
          <p id="workflow-timezone-hint" className="text-destructive text-xs">
            {t("settingsTimezoneUnknown", { zone })}
          </p>
        ) : (
          <p id="workflow-timezone-hint" className="text-muted-foreground text-xs">
            {t("settingsTimezoneNow", { time: now })} {t("settingsTimezoneHint")}
          </p>
        )}
      </div>

      <MoreOptions
        label={t("settingsExecution")}
        defaultOpen={saved.default_deadline_seconds !== null || saved.error_workflow_id !== null}
      >
        <div className="space-y-1.5">
          <Label htmlFor="workflow-deadline">{t("settingsDeadline")}</Label>
          <Input
            id="workflow-deadline"
            type="number"
            min={1 / 60}
            max={43_200}
            step="any"
            inputMode="decimal"
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
      </MoreOptions>
      <MoreOptions
        label={t("settingsHistory")}
        defaultOpen={saved.run_retention_days !== null || !saved.keep_succeeded_runs}
      >
        <div className="space-y-1.5">
          <Label htmlFor="workflow-retention">{t("settingsRetention")}</Label>
          <Input
            id="workflow-retention"
            type="number"
            min={1}
            max={3650}
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
      </MoreOptions>
      <MoreOptions
        label={t("settingsLimits")}
        defaultOpen={
          saved.max_concurrent_runs !== null ||
          saved.run_budget_usd !== null ||
          saved.monthly_budget_usd !== null
        }
      >
        <section className="space-y-4">
          <div className="space-y-1">
            <h3 className="text-sm font-medium">{t("settingsLimits")}</h3>
            <p className="text-muted-foreground text-xs">{t("settingsLimitsHint")}</p>
          </div>
          <div className="space-y-1.5">
            <Label htmlFor="workflow-concurrent">{t("settingsConcurrent")}</Label>
            <Input
              id="workflow-concurrent"
              type="number"
              min={1}
              max={1000}
              inputMode="numeric"
              placeholder={t("settingsNoLimit")}
              value={concurrent}
              disabled={disabled}
              onChange={(event) => setConcurrent(event.target.value)}
            />
            <p className="text-muted-foreground text-xs">{t("settingsConcurrentHint")}</p>
          </div>
          <div className="space-y-4">
            <div className="space-y-1.5">
              <Label htmlFor="workflow-run-budget">{t("settingsRunBudget")}</Label>
              <Input
                id="workflow-run-budget"
                type="number"
                min={0.000001}
                max={999_999}
                step="any"
                inputMode="decimal"
                placeholder={t("settingsNoLimit")}
                value={runBudget}
                disabled={disabled}
                onChange={(event) => setRunBudget(event.target.value)}
              />
              <p className="text-muted-foreground text-xs">{t("settingsRunBudgetHint")}</p>
            </div>
            <div className="space-y-1.5">
              <Label htmlFor="workflow-monthly-budget">{t("settingsMonthlyBudget")}</Label>
              <Input
                id="workflow-monthly-budget"
                type="number"
                min={0.000001}
                max={999_999}
                step="any"
                inputMode="decimal"
                placeholder={t("settingsNoLimit")}
                value={monthlyBudget}
                disabled={disabled}
                onChange={(event) => setMonthlyBudget(event.target.value)}
              />
              <p className="text-muted-foreground text-xs">{t("settingsMonthlyBudgetHint")}</p>
            </div>
          </div>
        </section>
      </MoreOptions>

      {!disabled && (
        <div className="bg-background sticky bottom-0 -mx-4 border-t px-4 py-4">
          <Button type="submit" disabled={saving || now === null}>
            {t("settingsSave")}
          </Button>
        </div>
      )}
    </form>
  );
}
