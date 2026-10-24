"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";

import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui";
import { useAgentEnvironments } from "@/hooks/use-agent-environments";
import { useEveryDataset } from "@/hooks/use-eval-runs";
import { useEvalSuites } from "@/hooks/use-eval-suites";
import { usePermissions } from "@/hooks/use-permissions";
import { ApiError, getErrorMessage } from "@/lib/api-error";
import { ROUTES } from "@/lib/constants";
import { DIALOG_FORM, DIALOG_SCROLL } from "@/lib/dialog-sizes";
import { useOrgStore } from "@/stores/org-store";
import type { EvalSuite, EvalSuiteInput, EvalSuiteSchedule } from "@/types/eval-suites";
import { Perm } from "@/types/permissions";
import { UngradedWarning } from "../estimate-summary";
import { usd } from "../format";
import { scheduleChoice, scheduleCron } from "./suite-format";
import {
  type SuiteForm,
  SuiteThresholdFields,
  SuiteWhatFields,
  SuiteWhenFields,
} from "./suite-form-fields";

/** How long the fields sit still before the estimate is asked for again. */
const ESTIMATE_DEBOUNCE_MS = 400;

/** The reader's own zone, which a new schedule is read in until they choose another. */
function browserZone(): string {
  return Intl.DateTimeFormat().resolvedOptions().timeZone;
}

function asText(value: number | null, scale = 1): string {
  return value === null ? "" : String(Math.round(value * scale * 100) / 100);
}

/** The form a suite opens with: its own settings, or a new suite's teaching defaults. */
export function formFor(suite: EvalSuite | undefined): SuiteForm {
  return {
    name: suite?.name ?? "",
    description: suite?.description ?? "",
    datasetId: suite?.dataset_id ?? "",
    environmentId: suite?.environment_id ?? null,
    onPublish: suite?.on_publish ?? true,
    onPromotion: suite?.on_promotion ?? false,
    onDependency: suite?.on_dependency_change ?? false,
    scheduled: suite ? suite.schedule !== null : false,
    schedule: scheduleChoice(suite?.schedule ?? null),
    timezone: suite?.schedule?.timezone ?? browserZone(),
    minPassRate: asText(suite?.threshold.min_pass_rate ?? null, 100),
    maxRegressions: String(suite?.threshold.max_confirmed_regressions ?? 0),
    costRise: asText(suite?.threshold.max_cost_per_pass_rise ?? null, 100),
    p95Rise: asText(suite?.threshold.max_p95_rise ?? null, 100),
    maxRunUsd: suite?.max_run_usd ?? "",
  };
}

/** A fraction from a typed percentage; empty is none. */
function fraction(text: string): number | null {
  return text.trim() === "" ? null : Number(text) / 100;
}

function scheduleOf(form: SuiteForm): EvalSuiteSchedule | null {
  return form.scheduled
    ? { cron: scheduleCron(form.schedule), timezone: form.timezone.trim() }
    : null;
}

/** What the form saves. */
export function inputFor(form: SuiteForm): EvalSuiteInput {
  return {
    name: form.name.trim(),
    description: form.description.trim() || null,
    dataset_id: form.datasetId,
    environment_id: form.environmentId,
    threshold: {
      min_pass_rate: fraction(form.minPassRate),
      max_confirmed_regressions: Number(form.maxRegressions || 0),
      max_cost_per_pass_rise: fraction(form.costRise),
      max_p95_rise: fraction(form.p95Rise),
    },
    on_publish: form.onPublish,
    on_promotion: form.onPromotion,
    on_dependency_change: form.onDependency,
    schedule: scheduleOf(form),
    max_run_usd: form.maxRunUsd.trim() || null,
  };
}

/**
 * Setting a suite up, or changing one: what it holds the agent to, when it runs,
 * and what a result must meet - with what a run, and a month of the schedule,
 * would cost before anything is saved.
 *
 * Scheduled runs start with nobody watching, so the estimate is the consent: a
 * suite runs as whoever saves it, and this is what they agree to spend.
 */
export function SuiteFormDialog({
  agentId,
  suite,
  onOpenChange,
}: {
  agentId: string;
  suite?: EvalSuite;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations("evals.suites.form");
  const tErrors = useTranslations("errors");
  const locale = useLocale();
  const { can } = usePermissions();
  const activeOrgId = useOrgStore((state) => state.activeOrgId);
  const [form, setForm] = useState<SuiteForm>(() => formFor(suite));
  const { datasets } = useEveryDataset();
  const { environments } = useAgentEnvironments(agentId);
  const { create, update, estimate } = useEvalSuites(agentId);
  const runnable = datasets.filter((dataset) => dataset.case_count > 0);
  const scheduleKey = JSON.stringify(scheduleOf(form));
  const { mutate: price } = estimate;

  useEffect(() => {
    if (!form.datasetId) return;
    const timer = setTimeout(
      () =>
        price({
          dataset_id: form.datasetId,
          environment_id: form.environmentId,
          schedule: JSON.parse(scheduleKey) as EvalSuiteSchedule | null,
        }),
      ESTIMATE_DEBOUNCE_MS,
    );
    return () => clearTimeout(timer);
  }, [form.datasetId, form.environmentId, scheduleKey, price]);

  const save = suite
    ? (input: EvalSuiteInput) => update.mutateAsync({ suiteId: suite.id, input })
    : (input: EvalSuiteInput) => create.mutateAsync(input);
  const saving = create.isPending || update.isPending;
  const failure = create.error ?? update.error ?? estimate.error;
  const assistanceOff =
    failure instanceof ApiError &&
    failure.details?.reason === "ai_assistance_off" &&
    can(Perm.orgSettings) &&
    activeOrgId !== null;
  const priced = estimate.data;
  const ready = form.name.trim() !== "" && form.datasetId !== "";

  return (
    <Dialog open onOpenChange={onOpenChange}>
      <DialogContent className={`${DIALOG_FORM} ${DIALOG_SCROLL}`}>
        <DialogHeader>
          <DialogTitle>{suite ? t("editTitle") : t("newTitle")}</DialogTitle>
          <DialogDescription>{t("intro")}</DialogDescription>
        </DialogHeader>
        <div className="space-y-6">
          <SuiteWhatFields
            form={form}
            onChange={(patch) => setForm({ ...form, ...patch })}
            datasets={runnable}
            environments={environments}
          />
          <SuiteWhenFields form={form} onChange={(patch) => setForm({ ...form, ...patch })} />
          <SuiteThresholdFields form={form} onChange={(patch) => setForm({ ...form, ...patch })} />
        </div>
        {priced && (
          <div className="bg-muted/50 space-y-1 rounded-lg p-3 text-sm">
            <p>
              {t("estimateRun", {
                amount: usd(
                  String(Number(priced.run.total_usd) + Number(priced.run.rerun_ceiling_usd)),
                  locale,
                ),
                count: priced.run.cases,
              })}
            </p>
            {priced.paired_run && (
              <p className="text-muted-foreground text-xs">
                {t("estimatePaired", {
                  amount: usd(
                    String(
                      Number(priced.paired_run.total_usd) +
                        Number(priced.paired_run.rerun_ceiling_usd),
                    ),
                    locale,
                  ),
                })}
              </p>
            )}
            {priced.monthly_usd !== null && priced.fires_per_month !== null && (
              <p className="text-muted-foreground text-xs">
                {t("estimateMonth", {
                  amount: usd(priced.monthly_usd, locale),
                  count: priced.fires_per_month,
                })}
              </p>
            )}
            <p className="text-muted-foreground text-xs">{t("runsAsYou")}</p>
            <UngradedWarning count={priced.run.ungraded_cases} />
          </div>
        )}
        {failure && (
          <div role="alert" className="text-destructive space-y-1 text-sm">
            <p>{getErrorMessage(failure, tErrors)}</p>
            {assistanceOff && (
              <Link
                href={`${ROUTES.ORGS}/${activeOrgId}/members`}
                className="text-foreground underline underline-offset-4"
              >
                {t("enableAi")}
              </Link>
            )}
          </div>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t("cancel")}
          </Button>
          <Button
            disabled={!ready || saving}
            onClick={() =>
              void save(inputFor(form))
                .then(() => onOpenChange(false))
                .catch(() => undefined)
            }
          >
            {suite ? t("save") : t("create")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
