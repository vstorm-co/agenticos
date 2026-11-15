"use client";

import { useTranslations } from "next-intl";

import { Button, FormField, Input, MarkdownEditor } from "@/components/ui";
import { PipelineModelPicker } from "@/components/evals/pipeline-model-picker";
import { useModelProviders } from "@/hooks/use-model-providers";
import { MoreOptions } from "@/components/ui/more-options";
import { usePermissions } from "@/hooks/use-permissions";
import { Perm } from "@/types/permissions";
import type { DatasetScoring } from "@/types/scoring";
import type { RuleChecks } from "./criterion-rule";
import { RubricEditor } from "./rubric-editor";
import { ScorerRow } from "./scorer-row";

interface JudgeSettingsProps {
  judge: DatasetScoring["judge"];
  tagGroups?: { tags: string[]; cases: number }[];
  totalCases?: number;
  /** The judge as saved, against which a change of judge is noticed. */
  stored: DatasetScoring["judge"];
  defaultInstructions?: string;
  reference: DatasetScoring["reference"];
  onJudge: (judge: DatasetScoring["judge"]) => void;
  onReference: (reference: DatasetScoring["reference"]) => void;
  disabled: boolean;
  /** How many of the dataset's cases have a reference answer, as a sentence. */
  referenceCoverage: string;
  /** How many have a counter-example, which the judge checks while it or the reference is on. */
  counterExampleCoverage: string;
  /** The dataset's rules, which a criterion a rule can check offers to add to. */
  rules?: RuleChecks;
}

/** The dataset owns its grading model, instructions, criteria and reference comparison. */
export function JudgeSettings({
  judge,
  defaultInstructions,
  stored,
  reference,
  onJudge,
  onReference,
  disabled,
  referenceCoverage,
  counterExampleCoverage,
  tagGroups,
  totalCases,
  rules,
}: JudgeSettingsProps) {
  const t = useTranslations("datasets.scoring");
  const { profiles, profilesStatus } = useModelProviders();
  const { can } = usePermissions();
  const tAgent = useTranslations("pages.agents");
  const yesNo = judge.scale_max === 2 && judge.pass_at === 2;
  return (
    <>
      {(judge.model_profile_id !== stored.model_profile_id ||
        judge.instructions !== stored.instructions) && (
        <p role="status" className="text-muted-foreground text-sm">
          {t("judgeChanged")}
        </p>
      )}
      <div className="space-y-6">
        <PipelineModelPicker
          profiles={profiles}
          profilesStatus={profilesStatus}
          value={judge.model_profile_id}
          onChange={(model_profile_id) => onJudge({ ...judge, model_profile_id })}
          allowAdd={can(Perm.connectionsManage)}
          disabled={disabled}
        />
        <MoreOptions label={tAgent("instructions")} defaultOpen={judge.instructions !== null}>
          <MarkdownEditor
            label={tAgent("instructions")}
            toolbar={<h3 className="text-sm font-medium">{tAgent("instructions")}</h3>}
            value={judge.instructions ?? defaultInstructions ?? ""}
            onChange={(instructions) => onJudge({ ...judge, instructions })}
            rows={8}
            disabled={disabled}
            inertImages
          />
        </MoreOptions>
      </div>
      <ScorerRow
        label={t("scorer.criteria")}
        hint={t("judgeHint")}
        enabled={judge.enabled}
        onChange={({ enabled }) => onJudge({ ...judge, enabled })}
        disabled={disabled}
      >
        <div className="grid gap-4 sm:grid-cols-2">
          <FormField htmlFor="grading-scale" label={t("scaleMax")} description={t("scaleHelp")}>
            <Input
              type="number"
              min={2}
              max={10}
              value={judge.scale_max}
              onChange={(event) => onJudge({ ...judge, scale_max: Number(event.target.value) })}
              disabled={disabled}
            />
          </FormField>
          <FormField htmlFor="grading-pass" label={t("passAt")} description={t("passHelp")}>
            <Input
              type="number"
              min={1}
              max={judge.scale_max}
              value={judge.pass_at}
              onChange={(event) => onJudge({ ...judge, pass_at: Number(event.target.value) })}
              disabled={disabled}
            />
          </FormField>
        </div>
        {!yesNo && (
          <Button
            size="sm"
            variant="outline"
            disabled={disabled}
            onClick={() => onJudge({ ...judge, scale_max: 2, pass_at: 2 })}
          >
            {t("useYesNo")}
          </Button>
        )}
        <RubricEditor
          rules={rules}
          criteria={judge.criteria}
          tagGroups={tagGroups}
          totalCases={totalCases}
          onChange={(criteria) => onJudge({ ...judge, criteria })}
          disabled={disabled}
        />
      </ScorerRow>
      <ScorerRow
        label={t("scorer.reference")}
        hint={t("referenceHint")}
        enabled={reference.enabled}
        mustPass={reference.required}
        coverage={referenceCoverage}
        onChange={(next) => onReference({ ...reference, ...next })}
        disabled={disabled}
      />
      <div className="border-b pb-4 last:border-b-0 last:pb-0">
        <p className="text-sm font-medium">{t("counterExampleRow")}</p>
        <p className="text-muted-foreground text-xs">{t("counterExampleHint")}</p>
        <p className="text-muted-foreground mt-0.5 text-xs">{counterExampleCoverage}</p>
      </div>
    </>
  );
}
