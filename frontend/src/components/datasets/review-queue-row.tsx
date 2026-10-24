"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Badge } from "@/components/ui";
import { useEvalRun } from "@/hooks/use-eval-runs";
import { useAgentEvalSuites } from "@/hooks/use-eval-suites";
import { ReviewReevaluationNote } from "@/components/evals/review-reevaluation-note";
import type { NoteTarget } from "@/hooks/use-scoring";
import type { CaseScore } from "@/types/scoring";
import { ScoreCard, type Verdict } from "./score-card";
import { ScoreDecision } from "./score-decision";

interface Props {
  score: CaseScore;
  busy: boolean;
  linksRuns: boolean;
  onVerdict?: (verdict: Verdict) => void;
  onReview?: () => void;
  onRescore?: () => void;
  onNoteToCriterion?: (target: NoteTarget) => void;
}

/** Compact by default; a decided answer stays in place with its effect and criterion offer. */
export function ReviewQueueRow(props: Props) {
  const { score, busy, onVerdict, onNoteToCriterion, linksRuns } = props;
  const t = useTranslations("datasets.scoring");
  const [expanded, setExpanded] = useState(false);
  const decided = score.human_passed !== null;
  return (
    <div className="rounded-lg border">
      <details open={expanded} onToggle={(event) => setExpanded(event.currentTarget.open)}>
        <summary className="cursor-pointer space-x-2 px-4 py-3 text-sm">
          <Badge variant={score.outcome === false ? "destructive" : "secondary"}>
            {t(score.outcome === true ? "passed" : score.outcome === false ? "failed" : "unscored")}
          </Badge>
          <span className="font-medium break-words">
            {score.case_masked ? t("maskedConversation") : score.question}
          </span>
        </summary>
        {expanded && (
          <div className="px-3 pb-3">
            <ScoreCard {...props} />
          </div>
        )}
      </details>
      {decided && !expanded && (
        <div className="space-y-2 px-4 pb-3">
          <p role="status" className="text-sm">
            {t(score.human_passed ? "countsAsPassed" : "countsAsFailed")}
          </p>
          {linksRuns && score.eval_run_id && score.agent_id && (
            <ReviewEffect runId={score.eval_run_id} agentId={score.agent_id} />
          )}
          <ScoreDecision
            compact
            decided={score.human_passed}
            note={score.human_note}
            caseTags={score.case_tags}
            onVerdict={onVerdict}
            onNoteToCriterion={onNoteToCriterion}
            busy={busy}
          />
        </div>
      )}
    </div>
  );
}

function ReviewEffect({ runId, agentId }: { runId: string; agentId: string }) {
  const { run, error } = useEvalRun(runId);
  const { suites } = useAgentEvalSuites(agentId);
  const t = useTranslations("datasets.scoring.reviewEffect");
  const ts = useTranslations("evals.suites");
  if (error) return <p className="text-muted-foreground text-xs">{t("unavailable")}</p>;
  return (
    <div className="text-muted-foreground space-y-1 text-xs">
      {run?.review && <ReviewReevaluationNote review={run.review} />}
      <p>
        {run?.outcome?.verdict
          ? t("run", { verdict: t(`verdict.${run.outcome.verdict}`) })
          : run?.status === "completed"
            ? t("notCompared")
            : run && !["queued", "running"].includes(run.status)
              ? t("didNotComplete")
              : t("refreshing")}
      </p>
      {suites
        .filter((suite) => suite.last_result?.eval_run_id === runId)
        .map((suite) => (
          <p key={suite.id}>
            {t("suite", { name: suite.name, status: ts(`status.${suite.last_result!.status}`) })}
          </p>
        ))}
    </div>
  );
}
