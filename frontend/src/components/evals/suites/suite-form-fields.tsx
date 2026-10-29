"use client";

import { useId } from "react";
import { useTranslations } from "next-intl";

import {
  Input,
  Label,
  MoreOptions,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Textarea,
} from "@/components/ui";
import { WEEKDAYS } from "@/lib/trigger-format";
import type { AgentEnvironment } from "@/types/agents";
import type { Dataset } from "@/types/datasets";
import { Toggle } from "../start-eval-fields";
import type { ScheduleChoice, ScheduleFrequency } from "./suite-format";

/** The form as typed: numbers stay text until saved, so a half-typed one is not lost. */
export interface SuiteForm {
  name: string;
  description: string;
  datasetId: string;
  environmentId: string | null;
  onPublish: boolean;
  onPromotion: boolean;
  onDependency: boolean;
  scheduled: boolean;
  schedule: ScheduleChoice;
  timezone: string;
  /** Percent, as typed; empty asks for no minimum. */
  minPassRate: string;
  maxRegressions: string;
  costRise: string;
  p95Rise: string;
  maxRunUsd: string;
}

const CURRENT = "__current__";
const FREQUENCIES: ScheduleFrequency[] = ["daily", "weekdays", "weekly", "custom"];

interface FieldsProps {
  form: SuiteForm;
  onChange: (patch: Partial<SuiteForm>) => void;
}

function Field({
  label,
  hint,
  children,
}: {
  label: string;
  hint?: string;
  children: (id: string) => React.ReactNode;
}) {
  const id = useId();
  return (
    <div className="space-y-1.5">
      <Label htmlFor={id}>{label}</Label>
      {children(id)}
      {hint && <p className="text-muted-foreground text-xs">{hint}</p>}
    </div>
  );
}

/** What the suite holds the agent to: a name, a dataset, and which version it checks. */
export function SuiteWhatFields({
  form,
  onChange,
  datasets,
  environments,
}: FieldsProps & {
  datasets: Dataset[];
  environments: Pick<AgentEnvironment, "id" | "name" | "version">[];
}) {
  const t = useTranslations("evals.suites.form");
  return (
    <div className="space-y-4">
      <Field label={t("name")}>
        {(id) => (
          <Input
            id={id}
            value={form.name}
            maxLength={120}
            placeholder={t("namePlaceholder")}
            onChange={(event) => onChange({ name: event.target.value })}
          />
        )}
      </Field>
      <Field label={t("dataset")} hint={t("datasetHint")}>
        {(id) => (
          <Select value={form.datasetId} onValueChange={(datasetId) => onChange({ datasetId })}>
            <SelectTrigger id={id} aria-label={t("dataset")}>
              <SelectValue placeholder={t("datasetPlaceholder")} />
            </SelectTrigger>
            <SelectContent>
              {datasets.map((dataset) => (
                <SelectItem key={dataset.id} value={dataset.id}>
                  {t("datasetOption", { name: dataset.name, count: dataset.case_count })}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
      </Field>
      <Field label={t("environment")} hint={t("environmentHint")}>
        {(id) => (
          <Select
            value={form.environmentId ?? CURRENT}
            onValueChange={(value) => onChange({ environmentId: value === CURRENT ? null : value })}
          >
            <SelectTrigger id={id} aria-label={t("environment")}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={CURRENT}>{t("currentVersion")}</SelectItem>
              {environments.map((environment) => (
                <SelectItem key={environment.id} value={environment.id}>
                  {t("environmentOption", { name: environment.name, version: environment.version })}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
      </Field>
    </div>
  );
}

/** When it runs on its own: any of the events, and a schedule read in a time zone. */
export function SuiteWhenFields({ form, onChange }: FieldsProps) {
  const t = useTranslations("evals.suites.form");
  const tDays = useTranslations("triggers");
  const schedule = form.schedule;
  const setSchedule = (patch: Partial<ScheduleChoice>) =>
    onChange({ schedule: { ...schedule, ...patch } });
  return (
    <fieldset className="space-y-3">
      <legend className="text-sm font-medium">{t("when")}</legend>
      <Toggle
        checked={form.onPublish}
        onChange={(onPublish) => onChange({ onPublish })}
        label={t("onPublish")}
        hint={t("onPublishHint")}
      />
      <Toggle
        checked={form.onPromotion}
        onChange={(onPromotion) => onChange({ onPromotion })}
        label={t("onPromotion")}
        hint={t("onPromotionHint")}
      />
      <Toggle
        checked={form.onDependency}
        onChange={(onDependency) => onChange({ onDependency })}
        label={t("onDependency")}
        hint={t("onDependencyHint")}
      />
      <Toggle
        checked={form.scheduled}
        onChange={(scheduled) => onChange({ scheduled })}
        label={t("onSchedule")}
        hint={t("onScheduleHint")}
      />
      {form.scheduled && (
        <div className="grid gap-3 pl-6 sm:grid-cols-2">
          <Field label={t("frequency")}>
            {(id) => (
              <Select
                value={schedule.frequency}
                onValueChange={(frequency) =>
                  setSchedule({ frequency: frequency as ScheduleFrequency })
                }
              >
                <SelectTrigger id={id} aria-label={t("frequency")}>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {FREQUENCIES.map((frequency) => (
                    <SelectItem key={frequency} value={frequency}>
                      {t(`frequencies.${frequency}`)}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
          </Field>
          {schedule.frequency === "custom" ? (
            <Field label={t("cron")} hint={t("cronHint")}>
              {(id) => (
                <Input
                  id={id}
                  value={schedule.cron}
                  className="font-mono"
                  onChange={(event) => setSchedule({ cron: event.target.value })}
                />
              )}
            </Field>
          ) : (
            <Field label={t("time")}>
              {(id) => (
                <Input
                  id={id}
                  type="time"
                  value={schedule.time}
                  onChange={(event) => setSchedule({ time: event.target.value })}
                />
              )}
            </Field>
          )}
          {schedule.frequency === "weekly" && (
            <Field label={t("weekday")}>
              {(id) => (
                <Select
                  value={String(schedule.weekday)}
                  onValueChange={(value) => setSchedule({ weekday: Number(value) })}
                >
                  <SelectTrigger id={id} aria-label={t("weekday")}>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {WEEKDAYS.map((day) => (
                      <SelectItem key={day.value} value={String(day.value)}>
                        {tDays(day.key)}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              )}
            </Field>
          )}
          <Field label={t("timezone")} hint={t("timezoneHint")}>
            {(id) => (
              <Input
                id={id}
                value={form.timezone}
                onChange={(event) => onChange({ timezone: event.target.value })}
              />
            )}
          </Field>
        </div>
      )}
    </fieldset>
  );
}

/** The threshold: quality up front, efficiency and the spend ceiling folded away. */
export function SuiteThresholdFields({ form, onChange }: FieldsProps) {
  const t = useTranslations("evals.suites.form");
  return (
    <fieldset className="space-y-4">
      <legend className="text-sm font-medium">{t("threshold")}</legend>
      <p className="text-muted-foreground text-xs">{t("thresholdHint")}</p>
      <div className="grid gap-4 sm:grid-cols-2">
        <Field label={t("maxRegressions")} hint={t("maxRegressionsHint")}>
          {(id) => (
            <Input
              id={id}
              type="number"
              min={0}
              inputMode="numeric"
              value={form.maxRegressions}
              onChange={(event) => onChange({ maxRegressions: event.target.value })}
            />
          )}
        </Field>
        <Field label={t("minPassRate")} hint={t("minPassRateHint")}>
          {(id) => (
            <Input
              id={id}
              type="number"
              min={0}
              max={100}
              inputMode="decimal"
              placeholder={t("none")}
              value={form.minPassRate}
              onChange={(event) => onChange({ minPassRate: event.target.value })}
            />
          )}
        </Field>
      </div>
      <MoreOptions label={t("advanced")}>
        <p className="text-muted-foreground text-xs">{t("efficiencyHint")}</p>
        <div className="grid gap-4 sm:grid-cols-2">
          <Field label={t("costRise")}>
            {(id) => (
              <Input
                id={id}
                type="number"
                min={0}
                inputMode="decimal"
                placeholder={t("none")}
                value={form.costRise}
                onChange={(event) => onChange({ costRise: event.target.value })}
              />
            )}
          </Field>
          <Field label={t("p95Rise")}>
            {(id) => (
              <Input
                id={id}
                type="number"
                min={0}
                inputMode="decimal"
                placeholder={t("none")}
                value={form.p95Rise}
                onChange={(event) => onChange({ p95Rise: event.target.value })}
              />
            )}
          </Field>
        </div>
        <Field label={t("maxRunUsd")} hint={t("maxRunUsdHint")}>
          {(id) => (
            <Input
              id={id}
              type="number"
              min={0}
              step="0.01"
              inputMode="decimal"
              placeholder={t("none")}
              value={form.maxRunUsd}
              onChange={(event) => onChange({ maxRunUsd: event.target.value })}
            />
          )}
        </Field>
        <Field label={t("description")}>
          {(id) => (
            <Textarea
              id={id}
              rows={2}
              maxLength={2000}
              value={form.description}
              onChange={(event) => onChange({ description: event.target.value })}
            />
          )}
        </Field>
      </MoreOptions>
    </fieldset>
  );
}
