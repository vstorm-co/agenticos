"use client";

import { PanelRightOpen } from "lucide-react";
import { useState } from "react";
import { useTranslations } from "next-intl";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetClose } from "@/components/ui";
import { useEvalRun } from "@/hooks/use-eval-runs";
import { useAgentEvalSuites } from "@/hooks/use-eval-suites";
import { ReviewReevaluationNote } from "@/components/evals/review-reevaluation-note";
import type { NoteTarget } from "@/hooks/use-scoring";
import type { CaseScore } from "@/types/scoring";
import { ScoreCard, type Verdict } from "./score-card";

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
  const { score, linksRuns } = props;
  const t = useTranslations("datasets.scoring");
  const [expanded, setExpanded] = useState(false);
  const decided = score.human_passed !== null;
  return (
    <div className="min-w-0">
      <button
        type="button"
        aria-haspopup="dialog"
        className="group flex min-h-10 w-full min-w-0 items-center justify-start gap-3 bg-transparent p-0 text-left text-sm font-medium whitespace-normal outline-none"
        onClick={() => setExpanded(true)}
      >
        <span className="line-clamp-2 min-w-0 flex-1 break-words">
          {score.case_masked ? t("maskedConversation") : score.question}
        </span>
        <PanelRightOpen className="text-muted-foreground size-3.5 shrink-0" aria-hidden />
      </button>
      <Sheet open={expanded} onOpenChange={setExpanded}>
        <SheetContent side="right" className="bg-background w-full sm:max-w-5xl">
          <SheetHeader className="shrink-0 py-4">
            <SheetTitle>{t("reviewCard.title")}</SheetTitle>
            <SheetClose onClick={() => setExpanded(false)} />
          </SheetHeader>
          <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-4 sm:p-6">
            {decided && (
              <p role="status" className="text-sm">
                {t(score.human_passed ? "countsAsPassed" : "countsAsFailed")}
              </p>
            )}
            <ScoreCard {...props} />
            {decided && linksRuns && score.eval_run_id && score.agent_id && (
              <ReviewEffect runId={score.eval_run_id} agentId={score.agent_id} />
            )}
          </div>
        </SheetContent>
      </Sheet>
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
