"use client";

import { useState, type ReactNode } from "react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { SettingsSection } from "@/components/settings/settings-section";
import {
  Button,
  FormField,
  Input,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Switch,
  Textarea,
} from "@/components/ui";
import { useModelProviders } from "@/hooks/use-model-providers";
import { useSetScoring } from "@/hooks/use-scoring";
import { getErrorMessage } from "@/lib/api-error";
import { scoringProblem } from "@/lib/scoring";
import type { CaseCheck } from "@/types/datasets";
import type { DatasetScoring, ReviewSelect } from "@/types/scoring";
import { RubricEditor } from "./rubric-editor";

const OWN_MODEL = "own";

/** The default checks' shape, shown in the empty box. Code, not copy: it is what is typed. */
const DEFAULTS_EXAMPLE = '[{"type": "max_cost_usd", "value": 0.05}]';

interface ScoringPanelProps {
  datasetId: string;
  scoring: DatasetScoring;
  /** Whether the caller may change it - `datasets:edit` on this dataset. */
  canEdit: boolean;
}

/** One scorer: whether it runs, and whether a case must pass it. */
function ScorerRow({
  label,
  hint,
  enabled,
  required,
  onChange,
  disabled,
  children,
}: {
  label: string;
  hint: string;
  enabled: boolean;
  required?: boolean;
  onChange: (next: { enabled: boolean; required?: boolean }) => void;
  disabled: boolean;
  children?: ReactNode;
}) {
  const t = useTranslations("datasets.scoring");
  return (
    <div className="space-y-3 border-b pb-4 last:border-b-0 last:pb-0">
      <div className="flex flex-wrap items-start gap-3">
        <Switch
          checked={enabled}
          onCheckedChange={(next) => onChange({ enabled: next, required })}
          aria-label={label}
          disabled={disabled}
        />
        <div className="min-w-0 flex-1">
          <p className="text-sm font-medium">{label}</p>
          <p className="text-muted-foreground text-xs">{hint}</p>
        </div>
        {required !== undefined && enabled && (
          <label className="flex items-center gap-2 text-xs">
            <Switch
              checked={required}
              onCheckedChange={(next) => onChange({ enabled, required: next })}
              aria-label={`${label}: ${t("required")}`}
              disabled={disabled}
            />
            {t("required")}
          </label>
        )}
      </div>
      {enabled && children}
    </div>
  );
}

/**
 * How a dataset's cases are scored, edited as one form and saved as a whole.
 *
 * The rule-based scorers cost nothing; the judge and the reference comparison
 * call the eval judge, which spends from its own budget and the organization's
 * and is refused while AI assistance is switched off. Scores already kept keep
 * the configuration they were computed with.
 */
export function ScoringPanel({ datasetId, scoring, canEdit }: ScoringPanelProps) {
  const t = useTranslations("datasets.scoring");
  const tErrors = useTranslations("errors");
  const save = useSetScoring(datasetId);
  const { profiles } = useModelProviders();
  const [draft, setDraft] = useState<DatasetScoring>(scoring);
  const [defaults, setDefaults] = useState(
    scoring.checks.defaults.length ? JSON.stringify(scoring.checks.defaults, null, 2) : "",
  );
  const [problem, setProblem] = useState<string | null>(null);
  const disabled = !canEdit || save.isPending;
  const unusable = scoringProblem(draft);
  const set = <K extends keyof DatasetScoring>(key: K, value: DatasetScoring[K]) =>
    setDraft((current) => ({ ...current, [key]: value }));

  const submit = async () => {
    let parsed: CaseCheck[] = [];
    try {
      parsed = defaults.trim() === "" ? [] : (JSON.parse(defaults) as CaseCheck[]);
    } catch {
      setProblem(t("defaultsNotJson"));
      return;
    }
    if (!Array.isArray(parsed)) {
      setProblem(t("defaultsNotJson"));
      return;
    }
    setProblem(null);
    try {
      await save.mutateAsync({ ...draft, checks: { ...draft.checks, defaults: parsed } });
      toast.success(t("saved"));
    } catch (failure) {
      toast.error(getErrorMessage(failure, tErrors));
    }
  };

  return (
    <SettingsSection
      title={t("title")}
      description={t("description")}
      action={
        canEdit ? (
          <Button size="sm" disabled={disabled || unusable !== null} onClick={() => void submit()}>
            {t("save")}
          </Button>
        ) : undefined
      }
    >
      <div className="space-y-4" data-tour="datasets-scoring">
        {canEdit && unusable !== null && (
          <p role="alert" className="text-destructive text-sm">
            {t(unusable)}
          </p>
        )}
        <ScorerRow
          label={t("scorer.check")}
          hint={t("checksHint")}
          enabled={draft.checks.enabled}
          required={draft.checks.required}
          onChange={(next) => set("checks", { ...draft.checks, ...next })}
          disabled={disabled}
        >
          <FormField htmlFor="scoring-defaults" label={t("defaults")} error={problem ?? undefined}>
            <Textarea
              id="scoring-defaults"
              value={defaults}
              onChange={(event) => setDefaults(event.target.value)}
              placeholder={DEFAULTS_EXAMPLE}
              className="font-mono text-xs"
              rows={3}
              disabled={disabled}
            />
          </FormField>
        </ScorerRow>

        <ScorerRow
          label={t("scorer.trajectory")}
          hint={t("trajectoryHint")}
          enabled={draft.trajectory.enabled}
          required={draft.trajectory.required}
          onChange={(next) => set("trajectory", { ...draft.trajectory, ...next })}
          disabled={disabled}
        />

        <ScorerRow
          label={t("scorer.judge")}
          hint={t("judgeHint")}
          enabled={draft.judge.enabled}
          onChange={({ enabled }) => set("judge", { ...draft.judge, enabled })}
          disabled={disabled}
        >
          <div className="grid gap-3 sm:grid-cols-3">
            <FormField htmlFor="scoring-judge-model" label={t("judgeModel")}>
              <Select
                value={draft.judge.model_profile_id ?? OWN_MODEL}
                onValueChange={(value) =>
                  set("judge", {
                    ...draft.judge,
                    model_profile_id: value === OWN_MODEL ? null : value,
                  })
                }
                disabled={disabled}
              >
                <SelectTrigger id="scoring-judge-model">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value={OWN_MODEL}>{t("judgeOwnModel")}</SelectItem>
                  {profiles.map((profile) => (
                    <SelectItem key={profile.id} value={profile.id}>
                      {profile.label}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </FormField>
            <FormField htmlFor="scoring-scale" label={t("scaleMax")}>
              <Input
                id="scoring-scale"
                type="number"
                min={2}
                max={10}
                value={draft.judge.scale_max}
                onChange={(event) =>
                  set("judge", { ...draft.judge, scale_max: Number(event.target.value) })
                }
                disabled={disabled}
              />
            </FormField>
            <FormField htmlFor="scoring-pass-at" label={t("passAt")}>
              <Input
                id="scoring-pass-at"
                type="number"
                min={1}
                max={draft.judge.scale_max}
                value={draft.judge.pass_at}
                onChange={(event) =>
                  set("judge", { ...draft.judge, pass_at: Number(event.target.value) })
                }
                disabled={disabled}
              />
            </FormField>
          </div>
          <RubricEditor
            criteria={draft.judge.criteria}
            onChange={(criteria) => set("judge", { ...draft.judge, criteria })}
            disabled={disabled}
          />
        </ScorerRow>

        <ScorerRow
          label={t("scorer.reference")}
          hint={t("referenceHint")}
          enabled={draft.reference.enabled}
          required={draft.reference.required}
          onChange={(next) => set("reference", { ...draft.reference, ...next })}
          disabled={disabled}
        />

        <FormField htmlFor="scoring-review" label={t("reviewSelect")}>
          <Select
            value={draft.review.select}
            onValueChange={(select) => set("review", { select: select as ReviewSelect })}
            disabled={disabled}
          >
            <SelectTrigger id="scoring-review">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="none">{t("review.none")}</SelectItem>
              <SelectItem value="failed">{t("review.failed")}</SelectItem>
              <SelectItem value="all">{t("review.all")}</SelectItem>
            </SelectContent>
          </Select>
        </FormField>
      </div>
    </SettingsSection>
  );
}
