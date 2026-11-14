"use client";

import Link from "next/link";
import { ROUTES } from "@/lib/constants";
import { useId } from "react";
import { useTranslations } from "next-intl";

import {
  Checkbox,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { MoreOptions } from "@/components/ui/more-options";
import { useAgentEnvironments } from "@/hooks/use-agent-environments";
import { cn } from "@/lib/utils";
import type { Dataset } from "@/types/datasets";
import type { EvalRunRequest } from "@/types/eval-runs";
import type { EvalTarget } from "./eval-target";

const NO_ENVIRONMENT = "none";
const DEFAULT_RERUNS = "default";
/** The API's own ceiling on confirming reruns. */
const MAX_RERUNS = 5;

/** The choice a run starts from, each option saying what it measures. */
export function TargetChoice({
  targets,
  value,
  currentVersion,
  draftDiffers,
  onChange,
}: {
  targets: EvalTarget[];
  value: EvalTarget | null;
  currentVersion: number | null;
  draftDiffers: boolean;
  onChange: (target: EvalTarget) => void;
}) {
  const t = useTranslations("evals.fields");
  const group = useId();
  if (targets.length === 0) {
    return <p className="text-muted-foreground text-sm">{t("noTarget")}</p>;
  }
  return (
    <fieldset className="min-w-0 space-y-2" data-tour="eval-target">
      <legend className="text-sm font-medium">{t("target")}</legend>
      <div className="grid gap-2 sm:grid-cols-2">
        {targets.map((target) => (
          <label
            key={target}
            className={cn(
              "has-[:focus-visible]:ring-ring grid min-w-0 cursor-pointer grid-cols-[auto_minmax(0,1fr)] content-start gap-x-3 gap-y-1 rounded-xl border p-3 transition-colors has-[:focus-visible]:ring-2",
              value === target
                ? "border-foreground/40 bg-accent/50"
                : "border-border hover:bg-accent/40",
              target === "compare" && !draftDiffers && "cursor-not-allowed opacity-50",
            )}
          >
            <input
              type="radio"
              name={group}
              value={target}
              checked={value === target}
              disabled={target === "compare" && !draftDiffers}
              onChange={() => onChange(target)}
              className="sr-only"
            />
            <span
              aria-hidden
              className={cn(
                "row-span-2 mt-0.5 flex size-4 shrink-0 items-center justify-center rounded-full border",
                value === target ? "border-primary bg-primary" : "border-muted-foreground/40",
              )}
            >
              {value === target && <span className="bg-primary-foreground size-1.5 rounded-full" />}
            </span>
            <span className="text-sm font-medium">
              {t(`targetOption.${target}`, { version: currentVersion ?? 0 })}
            </span>{" "}
            <span className="text-muted-foreground col-start-2 text-xs leading-relaxed">
              {target === "compare" && !draftDiffers
                ? t("noChanges")
                : t(`targetHint.${target}`, { version: currentVersion ?? 0 })}
            </span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}

export function Toggle({
  checked,
  onChange,
  label,
  hint,
}: {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label: string;
  hint: string;
}) {
  const id = useId();
  return (
    <label
      htmlFor={id}
      className={cn(
        "has-[:focus-visible]:ring-ring flex cursor-pointer items-start gap-3 rounded-lg border p-3 transition-colors has-[:focus-visible]:ring-2",
        checked ? "border-foreground/30 bg-accent/40" : "hover:bg-accent/30",
      )}
    >
      <Checkbox
        id={id}
        aria-labelledby={`${id}-label`}
        aria-describedby={`${id}-hint`}
        checked={checked}
        onCheckedChange={(value) => onChange(value === true)}
      />
      <span className="min-w-0 space-y-1">
        <span id={`${id}-label`} className="block text-sm font-medium">
          {label}
        </span>
        <span id={`${id}-hint`} className="text-muted-foreground block text-xs leading-relaxed">
          {hint}
        </span>
      </span>
    </label>
  );
}

/**
 * The dataset a run answers, and - folded away, because the defaults are
 * right for nearly every run - the environment, recordings and reruns.
 */
export function StartEvalFields({
  agentId,
  datasets,
  loading,
  datasetId,
  request,
  onChange,
  onOpenCases,
}: {
  agentId: string | null;
  /** The datasets with a case to run. */
  datasets: Dataset[];
  loading?: boolean;
  /** The dataset chosen or offered; empty while there is none to offer. */
  datasetId: string;
  request: EvalRunRequest;
  onChange: (next: EvalRunRequest) => void;
  onOpenCases: () => void;
}) {
  const t = useTranslations("evals.fields");
  const { environments } = useAgentEnvironments(agentId);
  const set = (patch: Partial<EvalRunRequest>) => onChange({ ...request, ...patch });

  return (
    <div className="space-y-4">
      <div className="space-y-1.5">
        <Label>{t("dataset")}</Label>
        <Select
          value={datasetId}
          onValueChange={(id) => set({ dataset_id: id })}
          disabled={loading || datasets.length === 0}
        >
          <SelectTrigger aria-label={t("dataset")}>
            <SelectValue placeholder={loading ? t("loadingDatasets") : t("datasetPlaceholder")} />
          </SelectTrigger>
          <SelectContent>
            {datasets.map((dataset) => (
              <SelectItem key={dataset.id} value={dataset.id} disabled={dataset.case_count === 0}>
                {t("datasetOption", {
                  name: dataset.name,
                  count: dataset.case_count,
                  version: dataset.latest_version,
                })}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {!loading && datasets.length === 0 && (
          <p className="text-muted-foreground text-sm">{t("noDatasets")}</p>
        )}
        {datasets.some((item) => item.id === datasetId && item.case_count === 0) && (
          <p className="text-muted-foreground text-sm">
            {t("emptyDataset")}{" "}
            <Link
              className="text-foreground underline underline-offset-4"
              href={`${ROUTES.DATASET_DETAIL(datasetId)}?tab=cases`}
              onClick={onOpenCases}
            >
              {t("openCases")}
            </Link>
          </p>
        )}
      </div>

      <MoreOptions label={t("advanced")}>
        <div className="space-y-4">
          <div className="space-y-1.5">
            <Label>{t("environment")}</Label>
            <Select
              value={request.environment_id ?? NO_ENVIRONMENT}
              onValueChange={(id) => set({ environment_id: id === NO_ENVIRONMENT ? null : id })}
            >
              <SelectTrigger aria-label={t("environment")}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={NO_ENVIRONMENT}>{t("noEnvironment")}</SelectItem>
                {environments.map((environment) => (
                  <SelectItem key={environment.id} value={environment.id}>
                    {environment.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="text-muted-foreground text-xs">{t("environmentHint")}</p>
          </div>
          <Toggle
            checked={request.from_recordings}
            onChange={(from_recordings) => set({ from_recordings })}
            label={t("fromRecordings")}
            hint={t("fromRecordingsHint")}
          />
          <div className="space-y-1.5">
            <Label>{t("reruns")}</Label>
            <Select
              value={String(request.reruns ?? DEFAULT_RERUNS)}
              onValueChange={(value) =>
                set({ reruns: value === DEFAULT_RERUNS ? null : Number(value) })
              }
            >
              <SelectTrigger aria-label={t("reruns")} className="w-40">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={DEFAULT_RERUNS}>{t("rerunsDefault")}</SelectItem>
                {Array.from({ length: MAX_RERUNS + 1 }, (_, n) => (
                  <SelectItem key={n} value={String(n)}>
                    {t("rerunsCount", { count: n })}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <p className="text-muted-foreground text-xs">{t("rerunsHint")}</p>
          </div>
        </div>
      </MoreOptions>
    </div>
  );
}
