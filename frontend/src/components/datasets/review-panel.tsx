"use client";

import { useState } from "react";
import { ClipboardCheck } from "lucide-react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { ErrorState, LoadingState } from "@/components/states";
import { Button, ListCard, ListCardEmpty, PAGE_SIZE, Pager } from "@/components/ui";
import { usePermissions } from "@/hooks/use-permissions";
import { type NoteTarget, useNoteToCriterion, useScores } from "@/hooks/use-scoring";
import { getErrorMessage } from "@/lib/api-error";
import type { Dataset } from "@/types/datasets";
import { Perm } from "@/types/permissions";
import type { CaseScore } from "@/types/scoring";
import { ReviewFilters, type ReviewFilter } from "./review-filters";
import { ReviewResultsTable } from "./review-results-table";
import type { Verdict } from "./score-card";
import { ReviewQueueRow } from "./review-queue-row";
import { useOrgStore } from "@/stores/org-store";

const OPENING: ReviewFilter = { outcome: null, agentId: null, tag: null };

/**
 * Every graded answer in the dataset, shown together with its source run.
 *
 * Grading happens elsewhere - an eval run, or a run graded against a case - so
 * this is where a person reads what the scorers said and decides what they were
 * unsure of. Results stay visible after a decision, which can be undone from
 * the toast that confirms it.
 */
export function ReviewPanel({ dataset }: { dataset: Dataset }) {
  const t = useTranslations("datasets.scoring");
  const tc = useTranslations("common");
  const tErrors = useTranslations("errors");
  const [filter, setFilter] = useState<ReviewFilter>(OPENING);
  const [page, setPage] = useState(0);
  const orgId = useOrgStore((state) => state.activeOrgId);
  const scope = JSON.stringify([orgId, dataset.id, page, filter]);
  const [kept, setKept] = useState<{
    scope: string;
    order: string[];
    scores: Record<string, { score: CaseScore; listing: CaseScore[] }>;
  }>({ scope, order: [], scores: {} });
  if (kept.scope !== scope) setKept({ scope, order: [], scores: {} });
  const scores = useScores(dataset.id, {
    pending: false,
    ...filter,
    skip: page * PAGE_SIZE,
    limit: PAGE_SIZE,
  });
  const { can } = usePermissions();
  // An eval run's page and Activity both refuse a reader without `runs:view`.
  const linksRuns = can(Perm.runsView);
  const canDecide = dataset.can_edit;
  // Scoring again reads the answer back from its run; `can_run` already holds `runs:view`.
  const canRescore = dataset.can_run;
  const toCriterion = useNoteToCriterion(dataset);
  const currentKept = kept.scope === scope ? kept : { order: [], scores: {} };
  const visible = new Map(scores.scores.map((score) => [score.id, score]));
  for (const { score, listing } of Object.values(currentKept.scores)) {
    const fresh = visible.get(score.id);
    // Keep the optimistic decision only against the listing it replaced. A new
    // server listing owns remote decisions and privacy masks.
    if (!fresh || (listing === scores.scores && !fresh.case_masked && !fresh.answer_hidden))
      visible.set(score.id, score);
  }
  const ids = [...new Set([...currentKept.order, ...scores.scores.map((score) => score.id)])];
  const visibleScores = ids
    .map((id) => visible.get(id))
    .filter((score): score is CaseScore => score !== undefined);
  const pageCount = Math.max(
    1,
    Math.ceil(scores.total / PAGE_SIZE),
    Object.keys(currentKept.scores).length ? page + 1 : 1,
  );
  // A refreshed listing may lose its last page; keep pagination on an existing page.
  if (!scores.isLoading && !scores.verdict.isPending && page >= pageCount) setPage(pageCount - 1);
  const ungraded = visibleScores.filter((score) => score.unscored_reason !== null);
  const waiting = visibleScores.filter(
    (score) => score.review_state === "pending" && score.human_passed === null,
  );
  const busy =
    scores.verdict.isPending ||
    scores.review.isPending ||
    scores.withdraw.isPending ||
    scores.rescore.isPending ||
    toCriterion.isPending;

  const decide = async (score: CaseScore, verdict: Verdict) => {
    try {
      const decided = await scores.verdict.mutateAsync({ scoreId: score.id, ...verdict });
      setKept((before) =>
        before.scope !== scope
          ? before
          : {
              ...before,
              order: before.order.length ? before.order : visibleScores.map((item) => item.id),
              scores: {
                ...before.scores,
                [decided.id]: { score: decided, listing: scores.scores },
              },
            },
      );
      const undo = () =>
        void decide(decided, { passed: score.human_passed, note: score.human_note });
      toast.success(verdict.passed === null ? t("verdictWithdrawn") : t("verdictSaved"), {
        action: { label: t("undo"), onClick: undo },
      });
    } catch (failure) {
      toast.error(getErrorMessage(failure, tErrors));
    }
  };
  const queue = async (scoreId: string) => {
    try {
      const sent = await scores.review.mutateAsync(scoreId);
      if (sent.review_state === "pending") toast.success(t("sentToReview"));
      else toast.info(t("newerWaits"));
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
  const noteToCriterion = async (score: CaseScore, target: NoteTarget) => {
    try {
      await toCriterion.mutateAsync({ score, target });
      toast.success(
        typeof target === "object"
          ? t("noteAddedToTags", { tags: target.tags.join(", ") })
          : t(target === "case" ? "noteAddedToCase" : "noteAddedToRubric"),
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
    <div className="flex flex-1 flex-col gap-4">
      <ListCard
        fill
        title={t("scores")}
        counted={t("scoreCount", { count: scores.total })}
        contentClassName="p-0"
        controls={
          <ReviewFilters
            filter={filter}
            onChange={(next) => {
              setFilter(next);
              setPage(0);
            }}
            tags={dataset.stats.top_tags.map((entry) => entry.tag)}
          />
        }
      >
        {scores.isLoading ? (
          <LoadingState variant="pending" />
        ) : scores.error ? (
          <ErrorState
            description={getErrorMessage(scores.error, tErrors)}
            cta={{ label: tc("retry"), onClick: () => void scores.refetch() }}
          />
        ) : visibleScores.length === 0 ? (
          <ListCardEmpty
            icon={ClipboardCheck}
            title={t("noScores")}
            description={t("noScoresBody")}
          />
        ) : (
          <div className="space-y-4">
            {((canRescore && ungraded.length > 1) || (canDecide && waiting.length > 0)) && (
              <div className="flex flex-wrap justify-end gap-2 px-4">
                {canRescore && ungraded.length > 1 && (
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={busy}
                    onClick={() => void rescore(ungraded.map((score) => score.id))}
                  >
                    {t("rescoreGroup", { count: ungraded.length })}
                  </Button>
                )}
                {canDecide && waiting.length > 0 && (
                  <Button
                    variant="ghost"
                    size="sm"
                    disabled={busy}
                    onClick={() => void withdraw(waiting.map((score) => score.id))}
                  >
                    {t("withdrawGroup", { count: waiting.length })}
                  </Button>
                )}
              </div>
            )}
            <ReviewResultsTable
              scores={visibleScores}
              linksRuns={linksRuns}
              question={(score) => (
                <ReviewQueueRow
                  key={`${score.id}:${score.case_masked ?? false}:${score.answer_hidden}`}
                  score={score}
                  busy={busy}
                  linksRuns={linksRuns}
                  onVerdict={canDecide ? (verdict) => void decide(score, verdict) : undefined}
                  onReview={canDecide ? () => void queue(score.id) : undefined}
                  onRescore={canRescore ? () => void rescore([score.id]) : undefined}
                  onNoteToCriterion={
                    canDecide ? (target) => void noteToCriterion(score, target) : undefined
                  }
                />
              )}
            />
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
    </div>
  );
}
