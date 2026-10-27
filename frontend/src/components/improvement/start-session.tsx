"use client";
import { useCallback, useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Clock } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import {
  Button,
  Input,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { SystemAgentChoice } from "@/components/agents/system-agent-choice";
import { StartQuestionSet, StartSignals } from "./session-inputs";
import { TodayCheck } from "./today-check";
import { WriteQuestions } from "./write-questions";
import { usd } from "@/components/evals/format";
import { useDatasets } from "@/hooks/use-datasets";
import { useImprovements } from "@/hooks/use-improvements";
import { getErrorMessage } from "@/lib/api-error";
import { openImprovement } from "@/lib/improvement-steps";
import { useOrgStore } from "@/stores/org-store";
import type { ImprovementEstimate } from "@/types/improvement";

/**
 * Screen 0: the agent's own test set is chosen and priced before anything is
 * asked, so the one decision is Start improving. Another set, the spending limit
 * and the helper sit under Show details; an agent without a test set gets one
 * written here.
 */
export function StartSession({ agentId }: { agentId: string }) {
  const t = useTranslations("improvement");
  const tr = useTranslations("authoring.improve");
  const tErrors = useTranslations("errors");
  const locale = useLocale();
  const router = useRouter();
  const params = useSearchParams();
  const baselineFirst = params.get("baseline") === "1";
  const organizationId = useOrgStore((state) => state.activeOrgId);
  const datasets = useDatasets({ limit: 100 });
  const own = useDatasets({ agent: agentId, sort: "updated", limit: 5 });
  const sessions = useImprovements(agentId);
  const [chosen, setChosen] = useState<string | null>(params.get("dataset"));
  const [written, setWritten] = useState(0);
  const [helper, setHelper] = useState<string | null>(null);
  const [budget, setBudget] = useState<string | null>(null);
  const [quoted, setQuote] = useState<{ key: string; value: ImprovementEstimate } | null>(null);
  const [refusal, setRefusal] = useState<{ key: string; message: string } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [details, setDetails] = useState(false);
  // A set made for this agent wins over one it was only run against or guarded by.
  const runnable = own.datasets.filter((dataset) => dataset.can_run);
  const target =
    chosen ?? (runnable.find((dataset) => dataset.agent_id === agentId) ?? runnable[0])?.id ?? "";
  const body = {
    dataset_id: target,
    ...(helper ? { improver_agent_id: helper } : {}),
    max_iterations: 3,
  };
  const asked = JSON.stringify(body);
  const key = `${asked}:${written}`;
  const quote = quoted?.key === key ? quoted.value : null;
  const refused = refusal?.key === key ? refusal.message : null;
  const limit = budget ?? quote?.total_usd ?? "";
  const estimateSession = sessions.estimate.mutateAsync;
  // An estimate spends nothing, so the price and the time are on screen as soon
  // as there is something to price; only starting asks for a click.
  useEffect(() => {
    if (!target) return;
    let current = true;
    estimateSession(JSON.parse(asked)).then(
      (priced) => {
        if (current) setQuote({ key, value: priced });
      },
      (failure: unknown) => {
        if (current) setRefusal({ key, message: getErrorMessage(failure, tErrors) });
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
  const resume = params.get("resume") === "1";
  // A link to Improve cannot know which session is open, so it lands here to be sent on.
  useEffect(() => {
    if (resume && open) router.replace(`/agents/${agentId}/improve/${open.id}`);
  }, [resume, open, agentId, router]);
  const loading = own.isLoading && !chosen;
  return (
    <div className="space-y-6" data-tour="improvement-start">
      <p className="text-muted-foreground max-w-2xl text-sm">{t("intro")}</p>
      <StartSignals agentId={agentId} datasetId={target} />
      {sessions.error && <p role="alert">{getErrorMessage(sessions.error, tErrors)}</p>}
      {open && (
        <Link
          className="block rounded-lg border p-3 text-sm underline underline-offset-4"
          href={`/agents/${agentId}/improve/${open.id}`}
        >
          {t("resumeOpen", {
            date: new Date(open.created_at).toLocaleString(locale),
            status: t(`status.${open.status}`),
          })}
        </Link>
      )}
      <div className="max-w-xl space-y-3">
        {baselineFirst && <p className="font-medium">{t("baselineFirst")}</p>}
        {loading ? (
          <p role="status">{t("loading")}</p>
        ) : !target ? (
          <WriteQuestions agentId={agentId} onReady={questionsReady} />
        ) : (
          baselineFirst && <TodayCheck agentId={agentId} datasetId={target} />
        )}
        {refused !== null && (
          <p role="alert" className="text-destructive text-sm">
            {refused}
          </p>
        )}
        {target && <StartQuestionSet datasetId={target} />}
        {target && !quote && refused === null && <p role="status">{t("estimating")}</p>}
        {quote && (
          <section
            className="border-primary/30 bg-primary/5 space-y-3 rounded-xl border p-4"
            data-tour="improvement-quote"
          >
            <p className="flex items-start gap-2">
              <Clock className="text-primary mt-0.5 size-4 shrink-0" aria-hidden />
              {t("sessionQuote", {
                minutes: quote.estimated_minutes,
                cost: usd(quote.total_usd, locale),
                count: quote.cases,
                rounds: quote.max_iterations,
              })}
            </p>
            {quote.reason && <p role="status">{tr(`reason.${quote.reason}`)}</p>}
            <Button
              disabled={
                !quote.affordable ||
                quote.reason !== null ||
                !Number.isFinite(Number(limit)) ||
                Number(limit) <= 0 ||
                sessions.start.isPending
              }
              onClick={() =>
                void (async () => {
                  setError(null);
                  try {
                    const started = await sessions.start.mutateAsync({
                      ...body,
                      budget_usd: limit,
                    });
                    if (useOrgStore.getState().activeOrgId === organizationId)
                      router.push(`/agents/${agentId}/improve/${started.id}`);
                  } catch (failure) {
                    setError(getErrorMessage(failure, tErrors));
                  }
                })()
              }
            >
              {t("start")}
            </Button>
          </section>
        )}
        {error && (
          <p role="alert" className="text-destructive text-sm">
            {error}
          </p>
        )}
        <details
          className="rounded-xl border p-3"
          data-tour="improvement-details"
          onToggle={(event) => setDetails(event.currentTarget.open)}
        >
          <summary className="cursor-pointer text-sm font-medium">{t("showDetails")}</summary>
          <div className="mt-3 space-y-4">
            {quote && (
              <div className="text-muted-foreground space-y-1 text-sm">
                <p>{t("evidence", { count: quote.evidence_runs })}</p>
                {quote.knowledge_usd && Number(quote.knowledge_usd) > 0 && (
                  <p>{t("knowledgeEstimate", { cost: usd(quote.knowledge_usd, locale) })}</p>
                )}
              </div>
            )}
            <div className="space-y-2" data-tour="improvement-test-set">
              <Label htmlFor="improvement-target">{t("testSet")}</Label>
              <Select value={target} onValueChange={setChosen}>
                <SelectTrigger id="improvement-target">
                  <SelectValue placeholder={t("chooseQuestions")} />
                </SelectTrigger>
                <SelectContent>
                  {datasets.datasets
                    .filter((d) => d.can_run)
                    .map((d) => (
                      <SelectItem key={d.id} value={d.id}>
                        {d.name}
                      </SelectItem>
                    ))}
                </SelectContent>
              </Select>
              {datasets.error && <p role="alert">{getErrorMessage(datasets.error, tErrors)}</p>}
            </div>
            {quote && (
              <div className="space-y-2">
                <Label htmlFor="improvement-budget">{t("budget")}</Label>
                <Input
                  id="improvement-budget"
                  type="number"
                  min="0.000001"
                  step="0.01"
                  value={limit}
                  onChange={(e) => setBudget(e.target.value)}
                />
              </div>
            )}
            {details && target && !baselineFirst && (
              <TodayCheck agentId={agentId} datasetId={target} />
            )}
            <SystemAgentChoice kind="improver" value={helper} onChange={setHelper} wizard />
          </div>
        </details>
      </div>
    </div>
  );
}
