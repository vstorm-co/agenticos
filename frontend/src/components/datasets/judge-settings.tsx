"use client";

import { useState } from "react";
import { TriangleAlert } from "lucide-react";
import { useTranslations } from "next-intl";

import { ConfirmDialog, Input } from "@/components/ui";
import type { DatasetScoring } from "@/types/scoring";
import { JudgePicker } from "./judge-picker";
import { RubricEditor } from "./rubric-editor";
import { ScorerRow } from "./scorer-row";

interface JudgeSettingsProps {
  judge: DatasetScoring["judge"];
  tagGroups?: { tags: string[]; cases: number }[];
  totalCases?: number;
  /** The judge as saved, against which a change of judge is noticed. */
  stored: DatasetScoring["judge"];
  reference: DatasetScoring["reference"];
  onJudge: (judge: DatasetScoring["judge"]) => void;
  onReference: (reference: DatasetScoring["reference"]) => void;
  disabled: boolean;
  onCreate?: () => void;
  /** How many of the dataset's cases have a reference answer, as a sentence. */
  referenceCoverage: string;
  /** How many have a counter-example, which the judge checks while it or the reference is on. */
  counterExampleCoverage: string;
  /** Changed to put the cursor in the rubric's first criterion. */
  focusRubric?: number;
}

/**
 * Which judge grades the dataset, on which criteria and from which mark, and
 * whether it compares answers with the reference answer. The counter-example is
 * no switch of its own: it is checked whenever either is on. The judge's model is
 * shown with it and changed on the judge's own page, the one place it is set.
 *
 * Changing the judge is allowed and said: scores graded before name another
 * judge, so they no longer compare with the ones graded after.
 */
export function JudgeSettings({
  judge,
  stored,
  reference,
  onJudge,
  onReference,
  disabled,
  onCreate,
  referenceCoverage,
  counterExampleCoverage,
  focusRubric,
  tagGroups,
  totalCases,
}: JudgeSettingsProps) {
  const t = useTranslations("datasets.scoring");
  const [switching, setSwitching] = useState<string | null | undefined>(undefined);
  const changed = judge.agent_id !== stored.agent_id;
  // Moving away from the judge the scores were graded by is asked once; coming
  // back to it is not, since the scores compare again.
  const pick = (agentId: string | null) =>
    agentId === stored.agent_id ? onJudge({ ...judge, agent_id: agentId }) : setSwitching(agentId);

  return (
    <>
      <JudgePicker value={judge.agent_id} onChange={pick} disabled={disabled} onCreate={onCreate} />
      {switching !== undefined && (
        <ConfirmDialog
          open
          onOpenChange={() => setSwitching(undefined)}
          title={t("switchJudgeTitle")}
          description={t("switchJudgeBody")}
          confirmLabel={t("switchJudge")}
          onConfirm={() => {
            onJudge({ ...judge, agent_id: switching });
            setSwitching(undefined);
          }}
        />
      )}
      {changed && (
        <p role="status" className="text-muted-foreground flex items-start gap-2 text-xs">
          <TriangleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
          {t("judgeChanged")}
        </p>
      )}
      <ScorerRow
        label={t("scorer.criteria")}
        hint={t("judgeHint")}
        enabled={judge.enabled}
        onChange={({ enabled }) => onJudge({ ...judge, enabled })}
        disabled={disabled}
      >
        <p className="flex flex-wrap items-center gap-1.5 text-sm">
          {t.rich("scaleSentence", {
            top: () => (
              <Input
                type="number"
                min={2}
                max={10}
                aria-label={t("scaleMax")}
                className="h-8 w-16"
                value={judge.scale_max}
                onChange={(event) => onJudge({ ...judge, scale_max: Number(event.target.value) })}
                disabled={disabled}
              />
            ),
            mark: () => (
              <Input
                type="number"
                min={1}
                max={judge.scale_max}
                aria-label={t("passAt")}
                className="h-8 w-16"
                value={judge.pass_at}
                onChange={(event) => onJudge({ ...judge, pass_at: Number(event.target.value) })}
                disabled={disabled}
              />
            ),
          })}
        </p>
        <RubricEditor
          criteria={judge.criteria}
          tagGroups={tagGroups}
          totalCases={totalCases}
          onChange={(criteria) => onJudge({ ...judge, criteria })}
          disabled={disabled}
          focusKey={focusRubric}
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
