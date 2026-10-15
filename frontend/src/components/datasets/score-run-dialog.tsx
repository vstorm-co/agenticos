"use client";

import { useState } from "react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";

import { ErrorState } from "@/components/states";
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
import { Pager, SearchInput, useDebounced } from "@/components/ui/list-controls";
import { useDatasetCases, useDatasets } from "@/hooks/use-datasets";
import { useRunTranscript } from "@/hooks/use-runs";
import { useScoreRun } from "@/hooks/use-scoring";
import { getErrorMessage } from "@/lib/api-error";
import { ROUTES } from "@/lib/constants";
import { callsJudge } from "@/lib/scoring";
import { DIALOG_SCROLL, DIALOG_WIDE } from "@/lib/dialog-sizes";
import type { DatasetCase } from "@/types/datasets";
import type { CaseScore, DatasetScoring } from "@/types/scoring";
import { AddToDatasetDialog } from "./add-to-dataset-dialog";
import { ScoreCard } from "./score-card";

/** As many as the server lists at once; past it the dataset picker searches and the case picker pages. */
const SHOWN = 100;

const SCORERS = ["checks", "trajectory", "judge", "reference"] as const;
const SCORER_KEY = {
  checks: "check",
  trajectory: "trajectory",
  judge: "judge",
  reference: "reference",
} as const;

/** Which of a dataset's scorers a score runs, and whether scoring this case pays for a judge run. */
function ScorersToRun({
  scoring,
  kase,
}: {
  scoring: DatasetScoring;
  kase: DatasetCase | undefined;
}) {
  const t = useTranslations("datasets.scoring");
  const locale = useLocale();
  const on = SCORERS.filter((scorer) => scoring[scorer].enabled);
  const names = new Intl.ListFormat(locale, { type: "conjunction" }).format(
    on.map((scorer) => t(`scorer.${SCORER_KEY[scorer]}`)),
  );
  return (
    <p className="text-muted-foreground text-xs">
      {t("willRun", { scorers: names })}
      {kase !== undefined && callsJudge(scoring, kase) && ` ${t("judgeSpends")}`}
    </p>
  );
}

interface ScoreRunDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  runId: string;
}

/** The run's own question and answer, the last of each it recorded. */
function useRunTurn(runId: string) {
  const { transcript } = useRunTranscript(runId, "run");
  const items = transcript?.items ?? [];
  const question = items.findLast((item) => item.role === "user")?.content.trim() ?? null;
  const answerId = items.findLast((item) => item.role === "assistant")?.id ?? null;
  return { question, answerId };
}

/**
 * Score one run's answer against a case of a dataset, and show what each scorer said.
 *
 * The run is read from Activity, so the answer and the tool calls are what it
 * recorded. The case asking the run's own question is picked when the dataset
 * has one; when it has none, the run's answer is offered as a new case instead.
 * Scoring keeps the result on the dataset, where a person can overrule it.
 */
export function ScoreRunDialog({ open, onOpenChange, runId }: ScoreRunDialogProps) {
  const t = useTranslations("datasets.scoring");
  const td = useTranslations("datasets");
  const tc = useTranslations("common");
  const tErrors = useTranslations("errors");
  const [search, setSearch] = useState("");
  const query = useDebounced(search);
  const listed = useDatasets({ search: query, sort: "updated", limit: SHOWN });
  const { datasets, isLoading } = listed;
  const [datasetId, setDatasetId] = useState("");
  const [caseId, setCaseId] = useState("");
  const [page, setPage] = useState(0);
  const [result, setResult] = useState<CaseScore | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const chosen = datasetId || datasets[0]?.id || "";
  const scoring = datasets.find((dataset) => dataset.id === chosen)?.scoring;
  const listing = useDatasetCases(chosen, { skip: page * SHOWN, limit: SHOWN });
  const { cases } = listing;
  const { question, answerId } = useRunTurn(runId);
  const [adding, setAdding] = useState(false);
  const asked = cases.find((item) => question !== null && item.input.trim() === question);
  const target = caseId || asked?.case_id || "";
  const kase = cases.find((item) => item.case_id === target);
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
        ) : listed.error ? (
          <ErrorState
            description={getErrorMessage(listed.error, tErrors)}
            cta={{ label: tc("retry"), onClick: () => void listed.refetch() }}
          />
        ) : !isLoading && datasets.length === 0 && query === "" ? (
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
            {(listed.total > datasets.length || search !== "") && (
              <SearchInput value={search} onChange={setSearch} placeholder={t("findDataset")} />
            )}
            <FormField htmlFor="score-dataset" label={td("dataset")}>
              <Select
                value={chosen}
                onValueChange={(next) => {
                  setDatasetId(next);
                  setCaseId("");
                  setPage(0);
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
                  <SelectValue
                    placeholder={
                      chosen === ""
                        ? t("pickDatasetFirst")
                        : listing.isLoading
                          ? t("loadingCases")
                          : cases.length === 0
                            ? t("noCaseToScore")
                            : t("pickCase")
                    }
                  />
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
            {question !== null && asked === undefined && !listing.isLoading && chosen !== "" && (
              <div className="text-muted-foreground flex flex-wrap items-center gap-2 text-xs">
                <span>{t("noCaseAsks")}</span>
                {answerId !== null && (
                  <Button
                    variant="link"
                    size="sm"
                    className="h-auto px-0"
                    onClick={() => setAdding(true)}
                  >
                    {t("addAsCase")}
                  </Button>
                )}
              </div>
            )}
            {listing.error ? (
              <ErrorState
                description={getErrorMessage(listing.error, tErrors)}
                cta={{ label: tc("retry"), onClick: () => void listing.refetch() }}
              />
            ) : (
              listing.total > SHOWN && (
                <Pager
                  page={page}
                  pageCount={Math.ceil(listing.total / SHOWN)}
                  matched={listing.total}
                  total={listing.total}
                  onPage={(next) => {
                    setPage(next);
                    setCaseId("");
                  }}
                  counted={td("caseCount", { count: listing.total })}
                />
              )
            )}
            {scoring !== undefined && <ScorersToRun scoring={scoring} kase={kase} />}
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
        {adding && answerId !== null && (
          <AddToDatasetDialog
            open
            onOpenChange={setAdding}
            messageId={answerId}
            answerAs="reference_answer"
            askAnswerAs
          />
        )}
      </DialogContent>
    </Dialog>
  );
}
