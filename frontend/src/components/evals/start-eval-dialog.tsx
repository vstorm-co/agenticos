"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
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
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import {
  useDatasetEvalRuns,
  useEvalRuns,
  useEveryAgent,
  useEveryDataset,
} from "@/hooks/use-eval-runs";
import { usePermissions } from "@/hooks/use-permissions";
import { ApiError, getErrorMessage } from "@/lib/api-error";
import { ROUTES } from "@/lib/constants";
import { isRunnable } from "@/lib/datasets";
import { DIALOG_FORM, DIALOG_SCROLL } from "@/lib/dialog-sizes";
import { useOrgStore } from "@/stores/org-store";
import type { EvalRunRequest } from "@/types/eval-runs";
import { Perm } from "@/types/permissions";
import { EstimateSummary } from "./estimate-summary";
import { type EvalTarget, TARGET_REQUEST, useEvalTarget } from "./eval-target";
import { usd } from "./format";
import { StartEvalFields, TargetChoice, Toggle } from "./start-eval-fields";

/** How long the fields sit still before the estimate is asked for again. */
const ESTIMATE_DEBOUNCE_MS = 400;

interface StartEvalDialogProps {
  /** The agent to test, or null to choose one here - a run started from a dataset. */
  agentId: string | null;
  /** The dataset to run, when the run starts from one. */
  datasetId?: string;
  /** What to test, when the caller already knows - the draft's own Test button. */
  target?: EvalTarget;
  onOpenChange: (open: boolean) => void;
}

const BLANK: EvalRunRequest = {
  dataset_id: "",
  candidate: "draft",
  model_profile_ids: [],
  paired_baseline: false,
  from_recordings: false,
  live_reads: false,
};

/**
 * Starting a run in the order that spends nothing by surprise: what to test and
 * on which dataset, already chosen where there is an obvious answer, then the
 * cost and what the budgets keep - priced as the fields settle - then run it.
 */
export function StartEvalDialog({
  agentId: givenAgent,
  datasetId: givenDataset,
  target: givenTarget,
  onOpenChange,
}: StartEvalDialogProps) {
  const t = useTranslations("evals");
  const tErrors = useTranslations("errors");
  const locale = useLocale();
  const router = useRouter();
  const { can } = usePermissions();
  const activeOrgId = useOrgStore((state) => state.activeOrgId);
  const [chosenAgent, setChosenAgent] = useState<string | null>(null);
  const [chosenTarget, setChosenTarget] = useState<EvalTarget | null>(givenTarget ?? null);
  // The version before runs beside the candidate when no earlier run of it compares.
  const [besideBaseline, setBesideBaseline] = useState(false);
  const [request, setRequest] = useState<EvalRunRequest>({
    ...BLANK,
    dataset_id: givenDataset ?? "",
  });
  const { agents } = useEveryAgent({ enabled: givenAgent === null });
  const { runs: datasetRuns } = useDatasetEvalRuns(givenDataset ?? "", {
    enabled: givenAgent === null && givenDataset !== undefined,
  });
  const testable = agents.filter((agent) => agent.kind !== "judge" && agent.can_run);
  // Started from a dataset: the agent last measured on it, else the only one there is.
  const offeredAgent =
    datasetRuns.find((run) => testable.some((agent) => agent.id === run.agent_id))?.agent_id ??
    (testable.length === 1 ? testable[0]?.id : undefined) ??
    null;
  const agentId = givenAgent ?? chosenAgent ?? offeredAgent;
  const { runs, estimate, start } = useEvalRuns(agentId);
  const { datasets } = useEveryDataset();
  const { currentVersion, targets, preferred } = useEvalTarget(agentId);

  const runnable = datasets.filter(isRunnable);
  const offered =
    runs.find((run) => runnable.some((dataset) => dataset.id === run.dataset_id))?.dataset_id ??
    (runnable.length === 1 ? runnable[0]?.id : undefined) ??
    "";
  const datasetId = request.dataset_id || offered;
  const target = chosenTarget !== null && targets.includes(chosenTarget) ? chosenTarget : preferred;
  const full: EvalRunRequest | null =
    agentId === null || target === null || datasetId === ""
      ? null
      : {
          ...request,
          dataset_id: datasetId,
          ...TARGET_REQUEST[target],
          ...(besideBaseline && target === "version" ? { paired_baseline: true } : {}),
        };
  // The fields as a value: a new object every render is not a new request.
  const asked = full === null ? null : JSON.stringify(full);

  const { mutate: quote, reset: clearQuote } = estimate;
  useEffect(() => {
    clearQuote();
    if (asked === null) return;
    const timer = setTimeout(
      () => quote(JSON.parse(asked) as EvalRunRequest),
      ESTIMATE_DEBOUNCE_MS,
    );
    return () => clearTimeout(timer);
  }, [asked, quote, clearQuote]);

  async function run(chosen: EvalRunRequest) {
    const created = await start.mutateAsync(chosen);
    onOpenChange(false);
    router.push(`${ROUTES.AGENTS}/${agentId}/evals/${created.id}`);
  }

  const failure = estimate.error ?? start.error;
  // Only the judge could decide a case and AI assistance is off: whoever may
  // turn it on is shown where.
  const assistanceOff =
    failure instanceof ApiError &&
    failure.details?.reason === "ai_assistance_off" &&
    can(Perm.orgSettings) &&
    activeOrgId !== null;
  // A quote is for the fields it was asked with; one still on screen while the
  // next is debounced must not be the price a click agrees to.
  const priced =
    asked !== null && JSON.stringify(estimate.variables) === asked ? estimate.data : undefined;
  const dataset = runnable.find((item) => item.id === datasetId);
  return (
    <Dialog open onOpenChange={onOpenChange}>
      <DialogContent className={`${DIALOG_FORM} ${DIALOG_SCROLL}`}>
        <DialogHeader>
          <DialogTitle>{t("startTitle")}</DialogTitle>
          <DialogDescription>{t("startBody")}</DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          {givenAgent === null && (
            <div className="space-y-1.5">
              <Label>{t("fields.agent")}</Label>
              <Select
                value={agentId ?? ""}
                onValueChange={(id) => {
                  setChosenAgent(id);
                  setChosenTarget(null);
                  // An environment is one agent's: another agent's would be refused.
                  setRequest(({ environment_id: _theirs, ...rest }) => rest);
                }}
              >
                <SelectTrigger aria-label={t("fields.agent")}>
                  <SelectValue placeholder={t("fields.agentPlaceholder")} />
                </SelectTrigger>
                <SelectContent>
                  {testable.map((agent) => (
                    <SelectItem key={agent.id} value={agent.id}>
                      {agent.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          )}
          {agentId !== null && (
            <TargetChoice
              targets={targets}
              value={target}
              currentVersion={currentVersion}
              onChange={setChosenTarget}
            />
          )}
          <StartEvalFields
            agentId={agentId}
            datasets={runnable}
            datasetId={datasetId}
            request={request}
            onChange={setRequest}
          />
        </div>
        {priced && agentId !== null && (
          <EstimateSummary
            agentId={agentId}
            estimate={priced}
            scoring={dataset?.scoring ?? null}
            judgeName={dataset?.judge_name ?? null}
          />
        )}
        {target === "version" && (besideBaseline || priced?.missing_baseline_version != null) && (
          <div className="space-y-2 text-sm">
            {!besideBaseline && <p className="text-warning text-xs">{t("noEarlierRun")}</p>}
            <Toggle
              checked={besideBaseline}
              onChange={setBesideBaseline}
              label={t("besideBaseline")}
              hint={t("besideBaselineHint")}
            />
          </div>
        )}
        {failure && (
          <div role="alert" className="text-destructive space-y-1 text-sm">
            <p>{getErrorMessage(failure, tErrors)}</p>
            {assistanceOff && (
              <Link
                href={`${ROUTES.ORGS}/${activeOrgId}/members`}
                className="text-foreground underline underline-offset-4"
              >
                {t("aiSettings")}
              </Link>
            )}
          </div>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t("cancel")}
          </Button>
          <Button
            data-tour="eval-run-start"
            disabled={!priced || !priced.affordable || start.isPending}
            onClick={() => full && void run(full).catch(() => undefined)}
          >
            {priced
              ? t("runFor", { amount: usd(priced.total_usd, locale) })
              : full !== null && !failure
                ? t("estimating")
                : t("start")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
