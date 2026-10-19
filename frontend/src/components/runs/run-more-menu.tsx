"use client";

import { useState } from "react";
import { ClipboardCheck, MoreHorizontal } from "lucide-react";
import { useTranslations } from "next-intl";

import { ScoreRunDialog } from "@/components/datasets/score-run-dialog";
import {
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui";

/**
 * The focused run's rarer actions. Today one: grading its answer against a case
 * of a dataset, which is rare beside reading the run and so not a button.
 *
 * The caller renders it only for somebody who may run a dataset's evals, and only
 * on a run with a transcript - without one there is no answer to grade.
 */
export function RunMoreMenu({ runId }: { runId: string }) {
  const t = useTranslations("pages.runs");
  const ts = useTranslations("datasets.scoring");
  const [scoring, setScoring] = useState(false);
  return (
    <>
      <DropdownMenu>
        <DropdownMenuTrigger asChild>
          <Button
            variant="outline"
            size="sm"
            aria-label={t("moreRunActions")}
            data-tour="runs-score-against-case"
          >
            <MoreHorizontal className="h-4 w-4" aria-hidden />
          </Button>
        </DropdownMenuTrigger>
        <DropdownMenuContent align="end">
          <DropdownMenuItem onSelect={() => setScoring(true)}>
            <ClipboardCheck className="h-4 w-4" aria-hidden />
            {ts("scoreRun")}
          </DropdownMenuItem>
        </DropdownMenuContent>
      </DropdownMenu>
      {scoring && <ScoreRunDialog open onOpenChange={setScoring} runId={runId} />}
    </>
  );
}
