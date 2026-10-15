"use client";

import { useState } from "react";
import { ClipboardCheck } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";
import { toast } from "sonner";

import { ErrorState, LoadingState } from "@/components/states";
import {
  ListCard,
  ListCardEmpty,
  PAGE_SIZE,
  Pager,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { useScores } from "@/hooks/use-scoring";
import { getErrorMessage } from "@/lib/api-error";
import { groupScores, type ScoreGroup } from "@/lib/scoring";
import { ScoreCard, type Verdict } from "./score-card";

type Showing = "pending" | "all";

interface ReviewPanelProps {
  datasetId: string;
  /** Whether the caller may decide - `datasets:edit` on this dataset. */
  canDecide: boolean;
}

/** Where a group of scores came from: one eval run, or grading by hand. */
function GroupHeading({ group }: { group: ScoreGroup }) {
  const t = useTranslations("datasets.scoring");
  const format = useFormatter();
  const [first] = group.scores;
  const when = format.dateTime(new Date(first!.created_at), {
    dateStyle: "medium",
    timeStyle: "short",
  });
  return (
    <h3 className="text-muted-foreground font-mono text-xs font-medium tracking-[0.1em] uppercase">
      {group.evalRunId === null ? t("groupByHand") : t("groupEvalRun", { when })}
      {" · "}
      {first!.agent_name ?? t("agentGone")}
    </h3>
  );
}

/**
 * A dataset's graded answers, waiting for a decision first, each eval run's together.
 *
 * Grading happens elsewhere - an eval run, or a run graded against a case - so
 * this is where a person reads what the scorers said and decides what they were
 * unsure of. Every result is a filter away.
 */
export function ReviewPanel({ datasetId, canDecide }: ReviewPanelProps) {
  const t = useTranslations("datasets.scoring");
  const tc = useTranslations("common");
  const tErrors = useTranslations("errors");
  const [showing, setShowing] = useState<Showing>("pending");
  const [page, setPage] = useState(0);
  const pending = showing === "pending";
  const scores = useScores(datasetId, { pending, skip: page * PAGE_SIZE, limit: PAGE_SIZE });
  const pageCount = Math.max(1, Math.ceil(scores.total / PAGE_SIZE));
  // A decision takes the last score off the last page of the queue; step back to
  // the page that still exists, the adjust-state-while-rendering way.
  if (!scores.isLoading && page >= pageCount) setPage(pageCount - 1);

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
        <Select
          value={showing}
          onValueChange={(next) => {
            setShowing(next as Showing);
            setPage(0);
          }}
        >
          <SelectTrigger
            className="w-56"
            aria-label={t("reviewFilter")}
            data-tour="datasets-review-filter"
          >
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="pending">{t("filterPending")}</SelectItem>
            <SelectItem value="all">{t("filterAll")}</SelectItem>
          </SelectContent>
        </Select>
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
          description={pending ? t("nothingAwaitingReviewBody") : t("noScoresBody")}
        />
      ) : (
        <div className="space-y-6">
          {groupScores(scores.scores).map((group, index) => (
            <section key={`${group.key}:${index}`} className="space-y-3">
              <GroupHeading group={group} />
              {group.scores.map((score) => (
                <ScoreCard
                  key={score.id}
                  score={score}
                  busy={scores.verdict.isPending || scores.review.isPending}
                  onVerdict={canDecide ? (verdict) => void decide(score.id, verdict) : undefined}
                  onReview={canDecide ? () => void queue(score.id) : undefined}
                />
              ))}
            </section>
          ))}
          <Pager
            page={page}
            pageCount={pageCount}
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
