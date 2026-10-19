"use client";

import Link from "next/link";
import { FlaskConical } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui";
import { isLive, useDraftEvalRuns } from "@/hooks/use-eval-runs";
import { ROUTES } from "@/lib/constants";
import { cn } from "@/lib/utils";
import { sideName } from "./names";
import { quoted } from "./verdict-headline";

/**
 * What the evals said about the draft about to be published: the verdict of
 * its last run, or that it was not tested since it last changed and the way to
 * test it. It informs; it does not hold the publish back.
 */
export function DraftEvalNote({ agentId, onTest }: { agentId: string; onTest: () => void }) {
  const t = useTranslations("evals");
  const { runs, isLoading } = useDraftEvalRuns(agentId);
  if (isLoading) return null;
  const [run] = runs;
  if (run === undefined) {
    return (
      <div className="flex flex-wrap items-center justify-between gap-2 rounded-md border px-3 py-2 text-sm">
        <span className="text-muted-foreground">{t("draftNote.untested")}</span>
        <Button size="sm" variant="outline" onClick={onTest}>
          <FlaskConical className="h-3.5 w-3.5" aria-hidden />
          {t("draftNote.test")}
        </Button>
      </div>
    );
  }
  const outcome = run.outcome;
  // What the draft's own answers left ungraded is undecided, not passed.
  const [ungraded, ...more] =
    run.arms.find((arm) => arm.id === outcome?.candidate_arm_id)?.ungraded_cases ?? [];
  const tone =
    outcome?.verdict === "worse"
      ? "border-destructive/40 text-destructive"
      : outcome?.verdict === "mixed" || ungraded
        ? "border-warning/40 text-warning"
        : outcome?.verdict === "better"
          ? "border-success/40 text-success"
          : "text-muted-foreground";
  return (
    <Link
      href={`${ROUTES.AGENTS}/${agentId}/evals/${run.id}`}
      className={cn(
        "block rounded-md border px-3 py-2 text-sm underline-offset-4 hover:underline",
        tone,
      )}
    >
      {outcome === null
        ? isLive(run.status)
          ? t("draftNote.running")
          : t("draftNote.unfinished", { status: run.status })
        : t("draftNote.result", {
            verdict: outcome.verdict ?? "first",
            baseline: outcome.baseline ? sideName(outcome.baseline, t) : "",
            broke: outcome.regressions_confirmed,
            fixed: outcome.fixed_confirmed,
          })}
      {ungraded && (
        <span className="mt-1 block">
          {t("draftNote.ungraded", {
            count: more.length + 1,
            question: quoted(ungraded.input),
            others: more.length,
          })}
        </span>
      )}
    </Link>
  );
}
