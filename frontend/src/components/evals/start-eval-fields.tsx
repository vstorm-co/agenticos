"use client";

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
import { useAgentEnvironments } from "@/hooks/use-agent-environments";
import { useDatasets } from "@/hooks/use-datasets";
import { useModelProviders } from "@/hooks/use-model-providers";
import type { EvalRunRequest } from "@/types/eval-runs";

/** The most models one run compares - the API's own ceiling. */
const MAX_MODELS = 4;
const NO_ENVIRONMENT = "none";

interface StartEvalFieldsProps {
  agentId: string;
  request: EvalRunRequest;
  onChange: (next: EvalRunRequest) => void;
  canRunDraft: boolean;
  currentVersion: number | null;
}

function Toggle({
  checked,
  onChange,
  label,
  hint,
}: {
  checked: boolean;
  onChange: (checked: boolean) => void;
  label: string;
  hint?: string;
}) {
  const id = useId();
  return (
    <div className="flex items-start gap-2">
      <Checkbox id={id} checked={checked} onCheckedChange={(value) => onChange(value === true)} />
      <div className="space-y-0.5">
        <Label htmlFor={id}>{label}</Label>
        {hint && <p className="text-muted-foreground text-xs">{hint}</p>}
      </div>
    </div>
  );
}

/** What a run is made of: the dataset, the candidate, the environment, the models. */
export function StartEvalFields({
  agentId,
  request,
  onChange,
  canRunDraft,
  currentVersion,
}: StartEvalFieldsProps) {
  const t = useTranslations("evals.fields");
  const { datasets } = useDatasets({ sort: "name", limit: 100 });
  const { environments } = useAgentEnvironments(agentId);
  const { profiles } = useModelProviders();
  const set = (patch: Partial<EvalRunRequest>) => onChange({ ...request, ...patch });
  const runnable = datasets.filter((dataset) => dataset.case_count > 0);

  return (
    <div className="space-y-4">
      <div className="space-y-1.5">
        <Label>{t("dataset")}</Label>
        <Select value={request.dataset_id} onValueChange={(id) => set({ dataset_id: id })}>
          <SelectTrigger aria-label={t("dataset")}>
            <SelectValue placeholder={t("datasetPlaceholder")} />
          </SelectTrigger>
          <SelectContent>
            {runnable.map((dataset) => (
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

      <div className="space-y-1.5">
        <Label>{t("candidate")}</Label>
        <Select
          value={request.candidate}
          onValueChange={(candidate) =>
            set({ candidate: candidate as EvalRunRequest["candidate"] })
          }
        >
          <SelectTrigger aria-label={t("candidate")}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {currentVersion !== null && (
              <SelectItem value="version">{t("published", { version: currentVersion })}</SelectItem>
            )}
            {canRunDraft && <SelectItem value="draft">{t("draft")}</SelectItem>}
          </SelectContent>
        </Select>
      </div>

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

      <fieldset className="space-y-2">
        <legend className="text-sm font-medium">{t("models")}</legend>
        <p className="text-muted-foreground text-xs">{t("modelsHint")}</p>
        {profiles.map((profile) => {
          const chosen = request.model_profile_ids.includes(profile.id);
          return (
            <Toggle
              key={profile.id}
              label={profile.label}
              checked={chosen}
              onChange={(checked) =>
                set({
                  model_profile_ids: checked
                    ? [...request.model_profile_ids, profile.id].slice(0, MAX_MODELS)
                    : request.model_profile_ids.filter((id) => id !== profile.id),
                })
              }
            />
          );
        })}
      </fieldset>

      <Toggle
        checked={request.paired_baseline}
        onChange={(paired_baseline) => set({ paired_baseline })}
        label={t("pairedBaseline")}
        hint={t("pairedBaselineHint")}
      />
      <Toggle
        checked={request.from_recordings}
        onChange={(from_recordings) => set({ from_recordings })}
        label={t("fromRecordings")}
        hint={t("fromRecordingsHint")}
      />
    </div>
  );
}
