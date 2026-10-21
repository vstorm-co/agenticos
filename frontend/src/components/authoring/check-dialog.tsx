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
  SelectGroup,
  SelectItem,
  SelectLabel,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { useEveryAgent, useEveryDataset } from "@/hooks/use-eval-runs";
import { useAgentEvalSuites } from "@/hooks/use-eval-suites";
import { getErrorMessage } from "@/lib/api-error";
import { DIALOG_FORM, DIALOG_SCROLL } from "@/lib/dialog-sizes";
import type { ProposalCheck } from "@/types/authoring";
import type { EvalRun, EvalRunEstimate } from "@/types/eval-runs";

/**
 * Check suggestions with evals before deciding them: pick one of the agent's eval
 * suites or a dataset - and, for a skill change, an agent that uses the skill -
 * see what it costs, and start.
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
  // `suite:<id>` or `dataset:<id>`: a suite brings its own dataset and environment.
  const [target, setTarget] = useState("");
  const [chosenAgent, setChosenAgent] = useState(agentId ?? "");
  const { suites } = useAgentEvalSuites(chosenAgent, { enabled: chosenAgent !== "" });
  const [kind, targetId] = target.split(":");
  const [quote, setQuote] = useState<{ key: string; value: EvalRunEstimate } | null>(null);
  const [refused, setRefused] = useState<{ key: string; message: string } | null>(null);
  const [startError, setStartError] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  const body: ProposalCheck = {
    ...(kind === "suite" ? { suite_id: targetId } : { dataset_id: targetId }),
    ...(agentId === null && { agent_id: chosenAgent }),
    ...(proposalId !== undefined && { proposal_id: proposalId }),
  };
  const ready = target !== "" && chosenAgent !== "";
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
          <DialogDescription>
            {proposalId === undefined ? t("body") : t("skillBody")}
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          {agentId === null && (
            <div className="space-y-1.5">
              <Label>{t("agent")}</Label>
              <Select
                value={chosenAgent}
                onValueChange={(agent) => {
                  setChosenAgent(agent);
                  // A suite belongs to the agent it was picked for.
                  if (kind === "suite") setTarget("");
                }}
              >
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
            <Label>{t("target")}</Label>
            <Select value={target} onValueChange={setTarget}>
              <SelectTrigger aria-label={t("target")}>
                <SelectValue placeholder={t("targetPlaceholder")} />
              </SelectTrigger>
              <SelectContent>
                {suites.length > 0 && (
                  <SelectGroup>
                    <SelectLabel>{t("suites")}</SelectLabel>
                    {suites.map((suite) => (
                      <SelectItem key={suite.id} value={`suite:${suite.id}`}>
                        {suite.dataset_name === null
                          ? suite.name
                          : `${suite.name} · ${suite.dataset_name}`}
                      </SelectItem>
                    ))}
                  </SelectGroup>
                )}
                <SelectGroup>
                  <SelectLabel>{t("datasets")}</SelectLabel>
                  {datasets.map((dataset) => (
                    <SelectItem key={dataset.id} value={`dataset:${dataset.id}`}>
                      {dataset.name}
                    </SelectItem>
                  ))}
                </SelectGroup>
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
