"use client";

import { useState } from "react";
import { ClipboardCheck } from "lucide-react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { ErrorState, LoadingState } from "@/components/states";
import { ListCard, ListCardEmpty, PAGE_SIZE, Pager, Switch } from "@/components/ui";
import { useScores } from "@/hooks/use-scoring";
import { getErrorMessage } from "@/lib/api-error";
import { ScoreCard, type Verdict } from "./score-card";

interface ScoresPanelProps {
  datasetId: string;
  /** Whether the caller may record verdicts - `datasets:edit` on this dataset. */
  canDecide: boolean;
}

/**
 * Every score kept for a dataset, newest first, with the review queue a toggle away.
 *
 * Scoring happens elsewhere - from a run in Activity, or by an eval run - so this
 * is where a person reads what the scorers said and overrules them when they are wrong.
 */
export function ScoresPanel({ datasetId, canDecide }: ScoresPanelProps) {
  const t = useTranslations("datasets.scoring");
  const tc = useTranslations("common");
  const tErrors = useTranslations("errors");
  const [pending, setPending] = useState(false);
  const [page, setPage] = useState(0);
  const scores = useScores(datasetId, { pending, skip: page * PAGE_SIZE, limit: PAGE_SIZE });

  const decide = async (scoreId: string, verdict: Verdict) => {
    try {
      await scores.verdict.mutateAsync({ scoreId, ...verdict });
      toast.success(verdict.passed === null ? t("verdictWithdrawn") : t("verdictSaved"));
    } catch (failure) {
      toast.error(getErrorMessage(failure, tErrors));
    }
  };
  const queue = async (scoreId: string) => {
    try {
      await scores.review.mutateAsync(scoreId);
      toast.success(t("sentToReview"));
    } catch (failure) {
      toast.error(getErrorMessage(failure, tErrors));
    }
  };

  return (
    <ListCard
      title={t("scores")}
      counted={t("scoreCount", { count: scores.total })}
      controls={
        <label className="flex items-center gap-2 text-sm" data-tour="datasets-review-filter">
          <Switch
            checked={pending}
            onCheckedChange={(next) => {
              setPending(next);
              setPage(0);
            }}
            aria-label={t("onlyAwaitingReview")}
          />
          {t("onlyAwaitingReview")}
        </label>
      }
    >
      {scores.isLoading ? (
        <LoadingState variant="skeleton-cards" rows={2} />
      ) : scores.error ? (
        <ErrorState
          description={getErrorMessage(scores.error, tErrors)}
          cta={{ label: tc("retry"), onClick: () => void scores.refetch() }}
        />
      ) : scores.scores.length === 0 ? (
        <ListCardEmpty
          icon={ClipboardCheck}
          title={pending ? t("nothingAwaitingReview") : t("noScores")}
          description={t("noScoresBody")}
        />
      ) : (
        <div className="space-y-4">
          {scores.scores.map((score) => (
            <ScoreCard
              key={score.id}
              score={score}
              busy={scores.verdict.isPending || scores.review.isPending}
              onVerdict={canDecide ? (verdict) => void decide(score.id, verdict) : undefined}
              onReview={canDecide ? () => void queue(score.id) : undefined}
            />
          ))}
          <Pager
            page={page}
            pageCount={Math.max(1, Math.ceil(scores.total / PAGE_SIZE))}
            matched={scores.total}
            total={scores.total}
            onPage={setPage}
            counted={t("scoreCount", { count: scores.total })}
          />
        </div>
      )}
    </ListCard>
  );
}
