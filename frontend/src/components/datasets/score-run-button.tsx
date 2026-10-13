"use client";

import { useState } from "react";
import { ClipboardCheck } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui";
import { ScoreRunDialog } from "./score-run-dialog";

/**
 * "Score against a case" on a run in Activity.
 *
 * The caller renders it only for somebody who may run a dataset's evals, and only
 * on a run with a transcript - without one there is no answer to score.
 */
export function ScoreRunButton({ runId }: { runId: string }) {
  const t = useTranslations("datasets.scoring");
  const [open, setOpen] = useState(false);
  return (
    <>
      <Button
        variant="outline"
        size="sm"
        data-tour="runs-score-against-case"
        onClick={() => setOpen(true)}
      >
        <ClipboardCheck className="h-4 w-4" aria-hidden />
        {t("scoreRun")}
      </Button>
      {open && <ScoreRunDialog open={open} onOpenChange={setOpen} runId={runId} />}
    </>
  );
}
