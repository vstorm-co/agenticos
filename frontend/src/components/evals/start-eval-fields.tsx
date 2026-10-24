"use client";

import { useId } from "react";
import { ChevronRight } from "lucide-react";
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
  if (targets.length === 0) {
    return <p className="text-muted-foreground text-sm">{t("noTarget")}</p>;
  }
  return (
    <div role="radiogroup" aria-label={t("target")} className="space-y-1" data-tour="eval-target">
      <p className="text-sm font-medium">{t("target")}</p>
      {targets.map((target) => (
        <button
          key={target}
          type="button"
          role="radio"
          aria-checked={value === target}
          disabled={target === "compare" && !draftDiffers}
          onClick={() => onChange(target)}
          className={cn(
            "min-h-11 w-full rounded-lg border px-3 py-2 text-left transition-colors disabled:cursor-not-allowed disabled:opacity-50",
            value === target ? "border-primary bg-primary/5" : "hover:bg-accent/40",
          )}
        >
          <span className="block text-sm font-medium">
            {t(`targetOption.${target}`, { version: currentVersion ?? 0 })}
          </span>
          <span className="text-muted-foreground block text-xs">
            {target === "compare" && !draftDiffers
              ? t("noChanges")
              : t(`targetHint.${target}`, { version: currentVersion ?? 0 })}
          </span>
        </button>
      ))}
    </div>
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
    <div className="flex items-start gap-2">
      <Checkbox id={id} checked={checked} onCheckedChange={(value) => onChange(value === true)} />
      <div className="space-y-0.5">
        <Label htmlFor={id}>{label}</Label>
        <p className="text-muted-foreground text-xs">{hint}</p>
      </div>
    </div>
  );
}

/**
 * The dataset a run answers, and - folded away, because the defaults are
 * right for nearly every run - the environment, recordings and reruns.
 */
export function StartEvalFields({
  agentId,
  datasets,
  datasetId,
  request,
  onChange,
}: {
  agentId: string | null;
  /** The datasets with a case to run. */
  datasets: Dataset[];
  /** The dataset chosen or offered; empty while there is none to offer. */
  datasetId: string;
  request: EvalRunRequest;
  onChange: (next: EvalRunRequest) => void;
}) {
  const t = useTranslations("evals.fields");
  const { environments } = useAgentEnvironments(agentId);
  const set = (patch: Partial<EvalRunRequest>) => onChange({ ...request, ...patch });

  return (
    <div className="space-y-4">
      <div className="space-y-1.5">
        <Label>{t("dataset")}</Label>
        <Select value={datasetId} onValueChange={(id) => set({ dataset_id: id })}>
          <SelectTrigger aria-label={t("dataset")}>
            <SelectValue placeholder={t("datasetPlaceholder")} />
          </SelectTrigger>
          <SelectContent>
            {datasets.map((dataset) => (
              <SelectItem key={dataset.id} value={dataset.id}>
                {t("datasetOption", {
                  name: dataset.name,
                  count: dataset.case_count,
                  version: dataset.latest_version,
                })}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>

      <details className="group border-border rounded-lg border">
        <summary className="flex cursor-pointer list-none items-center gap-1.5 p-3 text-sm">
          <ChevronRight className="h-3.5 w-3.5 transition-transform group-open:rotate-90" />
          {t("advanced")}
        </summary>
        <div className="space-y-4 border-t p-3">
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
      </details>
    </div>
  );
}
