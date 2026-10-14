"use client";

import { useState } from "react";
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
  FormField,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { useDatasetCases, useDatasets } from "@/hooks/use-datasets";
import { useScoreRun } from "@/hooks/use-scoring";
import { getErrorMessage } from "@/lib/api-error";
import { ROUTES } from "@/lib/constants";
import { DIALOG_SCROLL, DIALOG_WIDE } from "@/lib/dialog-sizes";
import type { CaseScore, DatasetScoring } from "@/types/scoring";
import { ScoreCard } from "./score-card";

const SCORERS = ["checks", "trajectory", "judge", "reference"] as const;
const SCORER_KEY = {
  checks: "check",
  trajectory: "trajectory",
  judge: "judge",
  reference: "reference",
} as const;

/** Which of a dataset's scorers a score runs, and that the judge's half is a paid run. */
function ScorersToRun({ scoring }: { scoring: DatasetScoring }) {
  const t = useTranslations("datasets.scoring");
  const locale = useLocale();
  const on = SCORERS.filter((scorer) => scoring[scorer].enabled);
  const names = new Intl.ListFormat(locale, { type: "conjunction" }).format(
    on.map((scorer) => t(`scorer.${SCORER_KEY[scorer]}`)),
  );
  return (
    <p className="text-muted-foreground text-xs">
      {t("willRun", { scorers: names })}
      {(scoring.judge.enabled || scoring.reference.enabled) && ` ${t("judgeSpends")}`}
    </p>
  );
}

interface ScoreRunDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  runId: string;
}

/**
 * Score one run's answer against a case of a dataset, and show what each scorer said.
 *
 * The run is read from Activity, so the answer and the tool calls are what it
 * recorded. Scoring keeps the result on the dataset, where a person can overrule it.
 */
export function ScoreRunDialog({ open, onOpenChange, runId }: ScoreRunDialogProps) {
  const t = useTranslations("datasets.scoring");
  const td = useTranslations("datasets");
  const tErrors = useTranslations("errors");
  const { datasets, isLoading } = useDatasets({ sort: "updated", limit: 100 });
  const [datasetId, setDatasetId] = useState("");
  const [caseId, setCaseId] = useState("");
  const [result, setResult] = useState<CaseScore | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const chosen = datasetId || datasets[0]?.id || "";
  const scoring = datasets.find((dataset) => dataset.id === chosen)?.scoring;
  const { cases } = useDatasetCases(chosen, { limit: 100 });
  const target = caseId || cases[0]?.case_id || "";
  const score = useScoreRun();

  async function submit() {
    setFailure(null);
    try {
      setResult(await score.mutateAsync({ datasetId: chosen, caseId: target, runId }));
    } catch (error) {
      setFailure(getErrorMessage(error, tErrors));
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className={`${DIALOG_WIDE} ${DIALOG_SCROLL}`}>
        <DialogHeader>
          <DialogTitle>{t("scoreRun")}</DialogTitle>
          <DialogDescription>{t("scoreRunBody")}</DialogDescription>
        </DialogHeader>
        {result !== null ? (
          <ScoreCard score={result} />
        ) : !isLoading && datasets.length === 0 ? (
          <p className="text-muted-foreground text-sm">
            {t.rich("noDatasetToScore", {
              link: (chunks) => (
                <Link href={ROUTES.DATASETS} className="underline">
                  {chunks}
                </Link>
              ),
            })}
          </p>
        ) : (
          <div className="space-y-4">
            <FormField htmlFor="score-dataset" label={td("dataset")}>
              <Select
                value={chosen}
                onValueChange={(next) => {
                  setDatasetId(next);
                  setCaseId("");
                }}
              >
                <SelectTrigger id="score-dataset">
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  {datasets.map((dataset) => (
                    <SelectItem key={dataset.id} value={dataset.id}>
                      {dataset.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </FormField>
            <FormField htmlFor="score-case" label={td("case")} error={failure}>
              <Select value={target} onValueChange={setCaseId} disabled={cases.length === 0}>
                <SelectTrigger id="score-case">
                  <SelectValue placeholder={t("noCaseToScore")} />
                </SelectTrigger>
                <SelectContent>
                  {cases.map((item) => (
                    <SelectItem key={item.case_id} value={item.case_id}>
                      {item.input.length > 80 ? `${item.input.slice(0, 80)}…` : item.input}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </FormField>
            {scoring !== undefined && <ScorersToRun scoring={scoring} />}
          </div>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {result === null ? td("cancel") : t("close")}
          </Button>
          {result === null && (
            <Button disabled={score.isPending || target === ""} onClick={() => void submit()}>
              {score.isPending ? t("scoring") : t("score")}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
