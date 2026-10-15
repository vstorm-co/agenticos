"use client";

import { TriangleAlert } from "lucide-react";
import { useTranslations } from "next-intl";

import {
  FormField,
  Input,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { useModelProviders } from "@/hooks/use-model-providers";
import type { DatasetScoring } from "@/types/scoring";
import { JudgePicker } from "./judge-picker";
import { RubricEditor } from "./rubric-editor";
import { ScorerRow } from "./scorer-row";

const OWN_MODEL = "own";

interface JudgeSettingsProps {
  judge: DatasetScoring["judge"];
  /** The judge as saved, against which a change of judge or model is noticed. */
  stored: DatasetScoring["judge"];
  reference: DatasetScoring["reference"];
  onJudge: (judge: DatasetScoring["judge"]) => void;
  onReference: (reference: DatasetScoring["reference"]) => void;
  disabled: boolean;
  onCreate?: () => void;
}

/**
 * Which judge grades the dataset, on which model, on which criteria and from
 * which mark, and whether it compares answers with the reference answer.
 *
 * Changing the judge or its model is allowed and said: scores graded before
 * name another judge, so they no longer compare with the ones graded after.
 */
export function JudgeSettings({
  judge,
  stored,
  reference,
  onJudge,
  onReference,
  disabled,
  onCreate,
}: JudgeSettingsProps) {
  const t = useTranslations("datasets.scoring");
  const { profiles } = useModelProviders();
  const changed =
    judge.agent_id !== stored.agent_id || judge.model_profile_id !== stored.model_profile_id;

  return (
    <>
      <JudgePicker
        value={judge.agent_id}
        onChange={(agent_id) => onJudge({ ...judge, agent_id })}
        disabled={disabled}
        onCreate={onCreate}
      />
      {changed && (
        <p role="status" className="text-muted-foreground flex items-start gap-2 text-xs">
          <TriangleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
          {t("judgeChanged")}
        </p>
      )}
      <ScorerRow
        label={t("scorer.judge")}
        hint={t("judgeHint")}
        enabled={judge.enabled}
        onChange={({ enabled }) => onJudge({ ...judge, enabled })}
        disabled={disabled}
      >
        <div className="grid gap-3 sm:grid-cols-3">
          <FormField htmlFor="scoring-judge-model" label={t("judgeModel")}>
            <Select
              value={judge.model_profile_id ?? OWN_MODEL}
              onValueChange={(value) =>
                onJudge({ ...judge, model_profile_id: value === OWN_MODEL ? null : value })
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
              value={judge.scale_max}
              onChange={(event) => onJudge({ ...judge, scale_max: Number(event.target.value) })}
              disabled={disabled}
            />
          </FormField>
          <FormField htmlFor="scoring-pass-at" label={t("passAt")}>
            <Input
              id="scoring-pass-at"
              type="number"
              min={1}
              max={judge.scale_max}
              value={judge.pass_at}
              onChange={(event) => onJudge({ ...judge, pass_at: Number(event.target.value) })}
              disabled={disabled}
            />
          </FormField>
        </div>
        <RubricEditor
          criteria={judge.criteria}
          onChange={(criteria) => onJudge({ ...judge, criteria })}
          disabled={disabled}
        />
      </ScorerRow>
      <ScorerRow
        label={t("scorer.reference")}
        hint={t("referenceHint")}
        enabled={reference.enabled}
        mustPass={reference.required}
        onChange={(next) => onReference({ ...reference, ...next })}
        disabled={disabled}
      />
    </>
  );
}
