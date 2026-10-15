"use client";

import { useState } from "react";
import { ClipboardCheck } from "lucide-react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { ErrorState, LoadingState } from "@/components/states";
import { ListCard, ListCardEmpty, PAGE_SIZE, Pager } from "@/components/ui";
import { usePermissions } from "@/hooks/use-permissions";
import { useScores } from "@/hooks/use-scoring";
import { getErrorMessage } from "@/lib/api-error";
import { groupScores } from "@/lib/scoring";
import type { Dataset } from "@/types/datasets";
import { Perm } from "@/types/permissions";
import type { CaseScore } from "@/types/scoring";
import { ReviewFilters, type ReviewFilter } from "./review-filters";
import { ReviewGroupHeading } from "./review-group";
import { ScoreCard, type Verdict } from "./score-card";

const OPENING: ReviewFilter = { pending: true, outcome: null, agentId: null, tag: null };

/**
 * A dataset's graded answers, waiting for a decision first, each eval run's together.
 *
 * Grading happens elsewhere - an eval run, or a run graded against a case - so
 * this is where a person reads what the scorers said and decides what they were
 * unsure of. Every result is a filter away, and a decision can be undone from
 * the toast that confirms it.
 */
export function ReviewPanel({ dataset }: { dataset: Dataset }) {
  const t = useTranslations("datasets.scoring");
  const tc = useTranslations("common");
  const tErrors = useTranslations("errors");
  const [filter, setFilter] = useState<ReviewFilter>(OPENING);
  const [page, setPage] = useState(0);
  const { pending, ...narrowed } = filter;
  const scores = useScores(dataset.id, {
    pending,
    ...narrowed,
    skip: page * PAGE_SIZE,
    limit: PAGE_SIZE,
  });
  const other = useScores(dataset.id, { pending: !pending, ...narrowed, limit: 1 });
  const { can } = usePermissions();
  const canDecide = dataset.can_edit;
  const canRescore = can(Perm.datasetsRun);
  const pageCount = Math.max(1, Math.ceil(scores.total / PAGE_SIZE));
  // A decision takes the last score off the last page of the queue; step back to
  // the page that still exists, the adjust-state-while-rendering way.
  if (!scores.isLoading && page >= pageCount) setPage(pageCount - 1);
  const busy =
    scores.verdict.isPending ||
    scores.review.isPending ||
    scores.withdraw.isPending ||
    scores.rescore.isPending;

  const decide = async (score: CaseScore, verdict: Verdict) => {
    try {
      await scores.verdict.mutateAsync({ scoreId: score.id, ...verdict });
      const undo = () =>
        void scores.verdict.mutateAsync({
          scoreId: score.id,
          passed: score.human_passed,
          note: score.human_note,
        });
      toast.success(verdict.passed === null ? t("verdictWithdrawn") : t("verdictSaved"), {
        action: { label: t("undo"), onClick: undo },
      });
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
  const rescore = async (scoreIds: string[]) => {
    try {
      const done = await scores.rescore.mutateAsync(scoreIds);
      toast.success(
        done.rescored.length > 0
          ? t("rescored", { count: done.rescored.length })
          : t("rescoreNothing"),
      );
    } catch (failure) {
      toast.error(getErrorMessage(failure, tErrors));
    }
  };
  const withdraw = async (scoreIds: string[]) => {
    try {
      await scores.withdraw.mutateAsync(scoreIds);
      toast.success(t("withdrawn", { count: scoreIds.length }));
    } catch (failure) {
      toast.error(getErrorMessage(failure, tErrors));
    }
  };

  return (
    <ListCard
      title={t("scores")}
      counted={t("scoreCount", { count: scores.total })}
      controls={
        <ReviewFilters
          filter={filter}
          onChange={(next) => {
            setFilter(next);
            setPage(0);
          }}
          waiting={pending ? scores.total : other.total}
          all={pending ? other.total : scores.total}
          tags={dataset.stats.top_tags.map((entry) => entry.tag)}
        />
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
              <ReviewGroupHeading
                group={group}
                busy={busy}
                onWithdraw={
                  canDecide && pending
                    ? () => void withdraw(group.scores.map((score) => score.id))
                    : undefined
                }
                onRescore={canRescore ? (ids) => void rescore(ids) : undefined}
              />
              {group.scores.map((score) => (
                <ScoreCard
                  key={score.id}
                  score={score}
                  busy={busy}
                  onVerdict={canDecide ? (verdict) => void decide(score, verdict) : undefined}
                  onReview={canDecide ? () => void queue(score.id) : undefined}
                  onRescore={canRescore ? () => void rescore([score.id]) : undefined}
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
