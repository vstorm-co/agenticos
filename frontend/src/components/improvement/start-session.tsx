"use client";
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";
import {
  Button,
  ConfirmDialog,
  DialogFooter,
  Input,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { cn } from "@/lib/utils";
import { DIALOG_BODY } from "@/lib/dialog-sizes";
import { StartQuestionSet, StartSignals } from "./session-inputs";
import { TodayCheck } from "./today-check";
import { WriteQuestions } from "./write-questions";
import { limitText, limitValue, sessionLimit, usd } from "@/components/evals/format";
import { useDatasets } from "@/hooks/use-datasets";
import { useAgentEvalSuites } from "@/hooks/use-eval-suites";
import { useImprovement, useImprovements } from "@/hooks/use-improvements";
import { subjectOf } from "@/lib/improvement-subject";
import { getErrorMessage, problemList } from "@/lib/api-error";
import { isActive, openImprovement } from "@/lib/improvement-steps";
import { useOrgStore } from "@/stores/org-store";
import type { Improvement, ImprovementEstimate } from "@/types/improvement";

/**
 * Configure a session over the Agent Builder, with its dataset and price visible.
 * The agent's own test set is preferred; the limit and detailed checks expand
 * when needed. Creating test questions has its own estimate before it starts.
 */
export function StartSession({ agentId, onClose }: { agentId: string; onClose: () => void }) {
  const t = useTranslations("improvement");
  const tc = useTranslations("common");
  const tr = useTranslations("authoring.improve");
  const tErrors = useTranslations("errors");
  const locale = useLocale();
  const router = useRouter();
  const params = useSearchParams();
  const mode = params.get("improve") ?? "";
  const baselineFirst = params.get("baseline") === "1" || mode.includes("baseline");
  const organizationId = useOrgStore((state) => state.activeOrgId);
  const datasets = useDatasets({ limit: 100 });
  const own = useDatasets({ agent: agentId, sort: "updated", limit: 5 });
  const sessions = useImprovements(agentId);
  const suites = useAgentEvalSuites(agentId);
  const [startedId, setStartedId] = useState<string | null>(null);
  const [chosen, setChosen] = useState<string | null>(
    params.get("improveDataset") ?? params.get("dataset"),
  );
  const [written, setWritten] = useState(0);
  const [budget, setBudget] = useState<string | null>(null);
  const [quoted, setQuote] = useState<{ key: string; value: ImprovementEstimate } | null>(null);
  const [refusal, setRefusal] = useState<{
    key: string;
    message: string;
    problems: string[] | null;
  } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [details, setDetails] = useState(false);
  // A set made for this agent wins over one it was only run against or guarded by.
  const runnable = own.datasets.filter((dataset) => dataset.can_run);
  const target =
    chosen ?? (runnable.find((dataset) => dataset.agent_id === agentId) ?? runnable[0])?.id ?? "";
  const body = {
    dataset_id: target,
    max_iterations: 3,
  };
  const asked = JSON.stringify(body);
  const key = `${asked}:${written}`;
  const quote = quoted?.key === key ? quoted.value : null;
  const refused = refusal?.key === key ? refusal.message : null;
  const limit = budget !== null ? limitValue(budget) : quote ? sessionLimit(quote) : "";
  const choices = [
    ...own.datasets,
    ...datasets.datasets.filter((dataset) => !own.datasets.some((item) => item.id === dataset.id)),
  ].filter((dataset) => dataset.can_run);
  const estimateSession = sessions.estimate.mutateAsync;
  // An estimate spends nothing, so the price and the time are on screen as soon
  // as there is something to price; only starting asks for a click.
  useEffect(() => {
    if (!target) return;
    let current = true;
    estimateSession(JSON.parse(asked)).then(
      (priced) => {
        if (current) {
          setQuote({ key, value: priced });
          setRefusal(null);
        }
      },
      (failure: unknown) => {
        if (current)
          setRefusal({
            key,
            message: getErrorMessage(failure, tErrors),
            problems: problemList(failure),
          });
      },
    );
    return () => {
      current = false;
    };
  }, [asked, key, target, estimateSession, tErrors]);
  const questionsReady = useCallback((datasetId: string) => {
    setChosen(datasetId);
    setWritten((count) => count + 1);
  }, []);
  const open = openImprovement(sessions.sessions);
  const resume = params.get("resume") === "1" || mode.includes("resume");
  // A link to Improve cannot know which session is open, so it lands here to be sent on.
  useEffect(() => {
    if (resume && open) router.replace(`/agents/${agentId}/improve/${open.id}`);
  }, [resume, open, agentId, router]);
  const loading = (own.isLoading || (runnable.length === 0 && datasets.isLoading)) && !chosen;
  const picker = (
    <div className="space-y-2" data-tour="improvement-test-set">
      <Label htmlFor="improvement-target">{t("startDataset")}</Label>
      <Select value={target} onValueChange={setChosen}>
        <SelectTrigger id="improvement-target">
          <SelectValue placeholder={t("chooseQuestions")} />
        </SelectTrigger>
        <SelectContent>
          {choices.map((dataset) => {
            const suite = suites.suites.find((item) => item.dataset_id === dataset.id);
            return (
              <SelectItem key={dataset.id} value={dataset.id}>
                {suite ? t("suiteSet", { name: dataset.name, suite: suite.name }) : dataset.name}
              </SelectItem>
            );
          })}
        </SelectContent>
      </Select>
      <p className="text-muted-foreground text-xs">{t("startDatasetHint")}</p>
    </div>
  );
  const writeOwn = (
    <details className="text-sm">
      <summary className="text-muted-foreground hover:text-foreground cursor-pointer">
        {t("writeOwnInstead")}
      </summary>
      <div className="mt-3">
        <WriteQuestions agentId={agentId} onReady={questionsReady} />
      </div>
    </details>
  );
  async function start() {
    setError(null);
    try {
      const started = await sessions.start.mutateAsync({ ...body, budget_usd: limit });
      setStartedId(started.id);
      if (useOrgStore.getState().activeOrgId === organizationId)
        router.push(`/agents/${agentId}/improve/${started.id}`);
    } catch (failure) {
      setError(getErrorMessage(failure, tErrors));
    }
  }
  return (
    <>
      <div className={cn(DIALOG_BODY, "space-y-5")} data-tour="improvement-start">
        {datasets.error && (
          <p role="alert" className="text-destructive-ink text-sm">
            {getErrorMessage(datasets.error, tErrors)}
          </p>
        )}
        {sessions.error && (
          <p role="alert" className="text-destructive-ink text-sm">
            {getErrorMessage(sessions.error, tErrors)}
          </p>
        )}
        {open && open.id !== startedId && (
          <div className="space-y-2 rounded-lg border p-3">
            <Link
              className="block text-sm underline underline-offset-4"
              href={`/agents/${agentId}/improve/${open.id}`}
            >
              {t("resumeOpen", {
                date: new Date(open.created_at).toLocaleString(locale),
                status: t(`status.${open.status}`),
              })}
            </Link>
            <EndOpen session={open} />
          </div>
        )}
        {baselineFirst && <p className="text-muted-foreground text-sm">{t("baselineFirst")}</p>}
        {loading ? (
          <p role="status" className="text-muted-foreground text-sm">
            {t("loading")}
          </p>
        ) : choices.length > 0 ? (
          <>
            {picker}
            {!target && writeOwn}
          </>
        ) : (
          <WriteQuestions agentId={agentId} onReady={questionsReady} />
        )}
        {refused !== null && (
          <div
            role="alert"
            className="bg-destructive/5 border-destructive/20 space-y-3 rounded-lg border p-4 text-sm"
          >
            <p className="text-destructive-ink font-medium">{refused}</p>
            {refusal?.problems && (
              <ul className="text-muted-foreground list-disc space-y-1 pl-5 break-words">
                {refusal.problems.map((problem) => (
                  <li key={problem}>{problem}</li>
                ))}
              </ul>
            )}
            {refusal?.problems && (
              <Button variant="outline" size="sm" asChild>
                <Link href={`/agents/${agentId}?tab=build`} onClick={onClose}>
                  {t("openAgent")}
                </Link>
              </Button>
            )}
          </div>
        )}
        {target && !quote && refused === null && (
          <p role="status" className="text-muted-foreground text-sm">
            {t("estimating")}
          </p>
        )}
        {quote && (
          <section className="space-y-3 rounded-lg border p-4" data-tour="improvement-quote">
            <dl className="grid grid-cols-2 gap-4">
              <div>
                <dt className="text-muted-foreground text-xs">{t("analysisEstimate")}</dt>
                <dd className="mt-1 text-lg font-semibold tabular-nums">
                  {usd(quote.total_usd, locale)}
                </dd>
              </div>
              <div>
                <dt className="text-muted-foreground text-xs">{t("budget")}</dt>
                <dd className="mt-1 text-lg font-semibold tabular-nums">
                  {Number.isFinite(Number(limit)) && Number(limit) > 0 ? usd(limit, locale) : "—"}
                </dd>
              </div>
            </dl>
            <p className="text-muted-foreground text-xs">
              {t("startCostHint", { cost: usd(quote.per_round_usd, locale) })}
            </p>
            {quote.reason && (
              <p role="status" className="text-sm">
                {tr(`reason.${quote.reason}`)}
              </p>
            )}
          </section>
        )}
        <StartSignals agentId={agentId} datasetId={target} />
        {target && (
          <details
            className="border-t pt-4"
            data-tour="improvement-details"
            onToggle={(event) => setDetails(event.currentTarget.open)}
          >
            <summary className="cursor-pointer text-sm font-medium">{t("showDetails")}</summary>
            <div className="mt-4 min-w-0 space-y-4">
              {choices.length > 0 && writeOwn}
              {quote && (
                <>
                  <p className="text-muted-foreground text-sm">
                    {t("sessionQuote", {
                      cost: usd(quote.total_usd, locale),
                      answers: quote.evidence_runs,
                      minutes: Math.max(
                        1,
                        Math.round(quote.estimated_minutes / quote.max_iterations),
                      ),
                      perRound: usd(quote.per_round_usd, locale),
                      limit: usd(limit, locale),
                    })}
                  </p>
                  <div className="space-y-1.5">
                    <Label htmlFor="improvement-budget">{t("budget")}</Label>
                    <Input
                      id="improvement-budget"
                      inputMode="decimal"
                      value={budget ?? limitText(sessionLimit(quote), locale)}
                      onChange={(event) => setBudget(event.target.value)}
                    />
                    <p className="text-muted-foreground text-xs">
                      {t("limitHint", {
                        analysis: usd(quote.total_usd, locale),
                        perRound: usd(quote.per_round_usd, locale),
                      })}
                    </p>
                  </div>
                  {quote.knowledge_usd && Number(quote.knowledge_usd) > 0 && (
                    <p className="text-muted-foreground text-sm">
                      {t("knowledgeEstimate", { cost: usd(quote.knowledge_usd, locale) })}
                    </p>
                  )}
                </>
              )}
              {target && (
                <StartQuestionSet datasetId={target} heldOut={quote?.held_out ?? undefined} />
              )}
              {details && target && <TodayCheck agentId={agentId} datasetId={target} />}
              {target && (
                <Link
                  className="text-sm underline underline-offset-4"
                  href={`/datasets/${target}?tab=settings`}
                >
                  {t("pipelineSettings")}
                </Link>
              )}
            </div>
          </details>
        )}
        {error && (
          <p role="alert" className="text-destructive-ink text-sm">
            {error}
          </p>
        )}
      </div>
      <DialogFooter className="border-t">
        <Button variant="outline" onClick={onClose}>
          {tc("cancel")}
        </Button>
        <Button
          loading={sessions.start.isPending}
          disabled={
            !quote ||
            !quote.affordable ||
            quote.reason !== null ||
            !Number.isFinite(Number(limit)) ||
            Number(limit) <= 0 ||
            startedId !== null
          }
          onClick={() => void start()}
        >
          {t("start")}
        </Button>
      </DialogFooter>
    </>
  );
}

/**
 * An agent has one open session at a time, so a new one starts only once the open
 * one ends: a working or failed session stops, one waiting for a decision is discarded.
 */
function EndOpen({ session }: { session: Improvement }) {
  const t = useTranslations("improvement.endOpen");
  const tErrors = useTranslations("errors");
  const actions = useImprovement(subjectOf(session), session.id);
  const [confirming, setConfirming] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const ending =
    isActive(session) || session.status === "failed" ? actions.cancel : actions.discard;
  return (
    <>
      <Button variant="outline" size="sm" onClick={() => setConfirming(true)}>
        {t("action")}
      </Button>
      <ConfirmDialog
        open={confirming}
        onOpenChange={setConfirming}
        title={t("title")}
        description={
          <>
            {t("body")}
            {error && (
              <span role="alert" className="text-destructive-ink mt-2 block">
                {error}
              </span>
            )}
          </>
        }
        confirmLabel={t("confirm")}
        loading={ending.isPending}
        onConfirm={async () => {
          setError(null);
          try {
            await ending.mutateAsync();
            setConfirming(false);
          } catch (failure) {
            setError(getErrorMessage(failure, tErrors));
          }
        }}
      />
    </>
  );
}
