"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";

import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui";
import { useEvalRuns } from "@/hooks/use-eval-runs";
import { getErrorMessage } from "@/lib/api-error";
import { ROUTES } from "@/lib/constants";
import { DIALOG_FORM, DIALOG_SCROLL } from "@/lib/dialog-sizes";
import type { EvalRunRequest } from "@/types/eval-runs";
import { EstimateSummary } from "./estimate-summary";
import { usd } from "./format";
import { StartEvalFields } from "./start-eval-fields";

interface StartEvalDialogProps {
  agentId: string;
  canRunDraft: boolean;
  currentVersion: number | null;
  onOpenChange: (open: boolean) => void;
}

/**
 * Starting a run, in the only order that spends nothing by surprise: choose
 * what runs, see what it costs and what the budgets keep, then run it.
 * Changing anything after the estimate asks for a new one.
 */
export function StartEvalDialog({
  agentId,
  canRunDraft,
  currentVersion,
  onOpenChange,
}: StartEvalDialogProps) {
  const t = useTranslations("evals");
  const tErrors = useTranslations("errors");
  const locale = useLocale();
  const router = useRouter();
  const { estimate, start } = useEvalRuns(agentId);
  const [request, setRequest] = useState<EvalRunRequest>({
    dataset_id: "",
    candidate: currentVersion === null ? "draft" : "version",
    model_profile_ids: [],
    paired_baseline: false,
    from_recordings: false,
    live_reads: false,
  });

  function change(next: EvalRunRequest) {
    setRequest(next);
    estimate.reset();
    start.reset();
  }

  async function run() {
    const created = await start.mutateAsync(request);
    onOpenChange(false);
    router.push(`${ROUTES.AGENTS}/${agentId}/evals/${created.id}`);
  }

  const failure = estimate.error ?? start.error;
  const quote = estimate.data;
  return (
    <Dialog open onOpenChange={onOpenChange}>
      <DialogContent className={`${DIALOG_FORM} ${DIALOG_SCROLL}`}>
        <DialogHeader>
          <DialogTitle>{t("startTitle")}</DialogTitle>
          <DialogDescription>{t("startBody")}</DialogDescription>
        </DialogHeader>
        <StartEvalFields
          agentId={agentId}
          request={request}
          onChange={change}
          canRunDraft={canRunDraft}
          currentVersion={currentVersion}
        />
        {quote && <EstimateSummary estimate={quote} />}
        {failure && (
          <p role="alert" className="text-destructive text-sm">
            {getErrorMessage(failure, tErrors)}
          </p>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t("cancel")}
          </Button>
          {quote ? (
            <Button
              data-tour="evals-run"
              disabled={!quote.affordable || start.isPending}
              onClick={() => void run().catch(() => undefined)}
            >
              {t("runFor", { amount: usd(quote.total_usd, locale) })}
            </Button>
          ) : (
            <Button
              disabled={request.dataset_id === "" || estimate.isPending}
              onClick={() => estimate.mutate(request)}
            >
              {t("estimateCost")}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
