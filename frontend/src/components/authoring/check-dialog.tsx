"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";

import { EstimateSummary } from "@/components/evals/estimate-summary";
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { useEveryAgent, useEveryDataset } from "@/hooks/use-eval-runs";
import { getErrorMessage } from "@/lib/api-error";
import { DIALOG_FORM, DIALOG_SCROLL } from "@/lib/dialog-sizes";
import type { ProposalCheck } from "@/types/authoring";
import type { EvalRun, EvalRunEstimate } from "@/types/eval-runs";

/**
 * Check suggestions with evals before deciding them: pick a dataset - and, for
 * a skill change, an agent that uses the skill - see what it costs, and start.
 *
 * The run measures the draft as it would be with every waiting suggestion, beside
 * the published version, and leaves out the cases taken from the suggestions'
 * own evidence. Nothing is accepted by checking.
 */
export function CheckDialog({
  agentId,
  proposalId,
  estimate,
  start,
  onStarted,
  onOpenChange,
}: {
  /** The agent the dataset runs on; null to pick one here, for a skill change. */
  agentId: string | null;
  proposalId?: string;
  estimate: (body: ProposalCheck) => Promise<EvalRunEstimate>;
  start: (body: ProposalCheck) => Promise<EvalRun>;
  onStarted: (run: EvalRun) => void;
  onOpenChange: (open: boolean) => void;
}) {
  const t = useTranslations("authoring.check");
  const tErrors = useTranslations("errors");
  const { datasets } = useEveryDataset();
  const { agents } = useEveryAgent({ enabled: agentId === null });
  const [datasetId, setDatasetId] = useState("");
  const [chosenAgent, setChosenAgent] = useState(agentId ?? "");
  const [quote, setQuote] = useState<{ key: string; value: EvalRunEstimate } | null>(null);
  const [refused, setRefused] = useState<{ key: string; message: string } | null>(null);
  const [startError, setStartError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const body: ProposalCheck = {
    dataset_id: datasetId,
    ...(agentId === null && { agent_id: chosenAgent }),
    ...(proposalId !== undefined && { proposal_id: proposalId }),
  };
  const ready = datasetId !== "" && chosenAgent !== "";
  const asked = JSON.stringify(body);

  useEffect(() => {
    if (!ready) return;
    let current = true;
    estimate(JSON.parse(asked) as ProposalCheck)
      .then((value) => current && setQuote({ key: asked, value }))
      .catch(
        (failure: unknown) =>
          current && setRefused({ key: asked, message: getErrorMessage(failure, tErrors) }),
      );
    return () => {
      current = false;
    };
  }, [asked, ready, estimate, tErrors]);

  // A quote is for the choices it was asked with; one still on screen while the
  // next is asked must not be the price a click agrees to.
  const priced = quote?.key === asked ? quote.value : null;
  const error = startError ?? (refused?.key === asked ? refused.message : null);

  async function run() {
    setStarting(true);
    setStartError(null);
    try {
      onStarted(await start(body));
    } catch (failure) {
      setStartError(getErrorMessage(failure, tErrors));
    } finally {
      setStarting(false);
    }
  }

  return (
    <Dialog open onOpenChange={onOpenChange}>
      <DialogContent className={`${DIALOG_FORM} ${DIALOG_SCROLL}`}>
        <DialogHeader>
          <DialogTitle>{t("title")}</DialogTitle>
          <DialogDescription>{t("body")}</DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          {agentId === null && (
            <div className="space-y-1.5">
              <Label>{t("agent")}</Label>
              <Select value={chosenAgent} onValueChange={setChosenAgent}>
                <SelectTrigger aria-label={t("agent")}>
                  <SelectValue placeholder={t("agentPlaceholder")} />
                </SelectTrigger>
                <SelectContent>
                  {agents.map((agent) => (
                    <SelectItem key={agent.id} value={agent.id}>
                      {agent.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}
          <div className="space-y-1.5">
            <Label>{t("dataset")}</Label>
            <Select value={datasetId} onValueChange={setDatasetId}>
              <SelectTrigger aria-label={t("dataset")}>
                <SelectValue placeholder={t("datasetPlaceholder")} />
              </SelectTrigger>
              <SelectContent>
                {datasets.map((dataset) => (
                  <SelectItem key={dataset.id} value={dataset.id}>
                    {dataset.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          {priced !== null && (
            <EstimateSummary
              agentId={chosenAgent}
              estimate={priced}
              scoring={null}
              judgeName={null}
            />
          )}
          {error !== null && (
            <p role="alert" className="text-destructive text-sm">
              {error}
            </p>
          )}
        </div>
        <DialogFooter>
          <Button variant="ghost" onClick={() => onOpenChange(false)}>
            {t("cancel")}
          </Button>
          <Button
            disabled={priced === null || !priced.affordable || starting}
            onClick={() => void run()}
          >
            {t("start")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
