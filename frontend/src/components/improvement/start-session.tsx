"use client";
import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
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
import { StartSignals } from "./session-inputs";
import { StartEvalDialog } from "@/components/evals/start-eval-dialog";
import { usd } from "@/components/evals/format";
import { useDatasets } from "@/hooks/use-datasets";
import { useAgentTestSet } from "@/hooks/use-agent-test-set";
import { useImprovements } from "@/hooks/use-improvements";
import { getErrorMessage } from "@/lib/api-error";
import { useOrgStore } from "@/stores/org-store";
import type { ImprovementEstimate } from "@/types/improvement";

export function StartSession({ agentId }: { agentId: string }) {
  const t = useTranslations("improvement");
  const tr = useTranslations("authoring.improve");
  const tErrors = useTranslations("errors");
  const locale = useLocale();
  const router = useRouter();
  const organizationId = useOrgStore((state) => state.activeOrgId);
  const datasets = useDatasets();
  const sessions = useImprovements(agentId);
  const testSet = useAgentTestSet(agentId);
  const [target, setTarget] = useState("");
  const [helper, setHelper] = useState<string | null>(null);
  const [budget, setBudget] = useState("");
  const [quoted, setQuote] = useState<{ key: string; value: ImprovementEstimate } | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [baseline, setBaseline] = useState(false);
  const [buildQuote, setBuildQuote] = useState<{ cost: string; priced: boolean } | null>(null);
  const body = {
    dataset_id: target,
    ...(helper ? { improver_agent_id: helper } : {}),
    max_iterations: 3,
  };
  const asked = JSON.stringify(body);
  const quote = quoted?.key === asked ? quoted.value : null;
  const [refusal, setRefusal] = useState<{ key: string; message: string } | null>(null);
  const refused = refusal?.key === asked ? refusal.message : null;
  const estimateSession = sessions.estimate.mutateAsync;
  // An estimate spends nothing, so the price and the time are on screen as soon
  // as there is something to price; only starting asks for a click.
  useEffect(() => {
    if (!target) return;
    let current = true;
    estimateSession(JSON.parse(asked)).then(
      (priced) => {
        if (!current) return;
        setQuote({ key: asked, value: priced });
        setBudget(priced.total_usd);
      },
      (failure: unknown) => {
        if (!current) return;
        setRefusal({ key: asked, message: getErrorMessage(failure, tErrors) });
      },
    );
    return () => {
      current = false;
    };
  }, [asked, target, estimateSession, tErrors]);
  async function act(action: () => Promise<void>) {
    setError(null);
    try {
      await action();
    } catch (e) {
      setError(getErrorMessage(e, tErrors));
    }
  }
  return (
    <div className="space-y-6" data-tour="improvement-start">
      <p className="text-muted-foreground max-w-2xl text-sm">{t("intro")}</p>
      <StartSignals agentId={agentId} datasetId={target} />
      {sessions.error && <p role="alert">{getErrorMessage(sessions.error, tErrors)}</p>}
      {sessions.sessions.map((session) => (
        <Link
          key={session.id}
          className="block rounded-lg border p-3 text-sm underline underline-offset-4"
          href={`/agents/${agentId}/improve/${session.id}`}
        >
          {t("resume", {
            date: new Date(session.created_at).toLocaleString(locale),
            status: t(`status.${session.status}`),
          })}
        </Link>
      ))}
      <div className="max-w-xl space-y-3">
        <div className="space-y-3" data-tour="improvement-test-set">
          <Label htmlFor="improvement-target">{t("testSet")}</Label>
          <Select
            value={target}
            onValueChange={(value) => {
              setTarget(value);
              setQuote(null);
              setBudget("");
            }}
          >
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
        </div>
        {datasets.error && <p role="alert">{getErrorMessage(datasets.error, tErrors)}</p>}
        <details className="rounded-lg border p-3">
          <summary className="cursor-pointer text-sm font-medium">{t("writeQuestions")}</summary>
          <div className="mt-3 space-y-3">
            <p className="text-muted-foreground text-sm">{t("questionCost")}</p>
            <Button
              variant="outline"
              disabled={testSet.estimate.isPending}
              onClick={() =>
                void act(async () => {
                  const q = await testSet.estimate.mutateAsync({ more: 12 });
                  setBuildQuote({ cost: q.cost_usd, priced: q.priced });
                })
              }
            >
              {t("estimateQuestions")}
            </Button>
            {buildQuote && (
              <>
                <p className="text-sm">
                  {t("estimatedCost", { cost: usd(buildQuote.cost, locale) })}
                </p>
                <Button
                  disabled={!buildQuote.priced || testSet.build.isPending}
                  onClick={() =>
                    void act(async () => {
                      const built = await testSet.build.mutateAsync({ more: 12 });
                      setTarget(built.dataset_id);
                      setQuote(null);
                      setBuildQuote(null);
                    })
                  }
                >
                  {t("confirmQuestions")}
                </Button>
              </>
            )}
            {testSet.build.data && (
              <p className="text-sm">
                {t("questionsQueued")}{" "}
                <Link className="underline" href={`/datasets/${testSet.build.data.dataset_id}`}>
                  {t("reviewQuestions")}
                </Link>
              </p>
            )}
          </div>
        </details>
        {target && (
          <Button variant="outline" onClick={() => setBaseline(true)}>
            {t("baseline")}
          </Button>
        )}
        <SystemAgentChoice
          kind="improver"
          value={helper}
          onChange={(value) => {
            setHelper(value);
            setQuote(null);
          }}
        />
        {refused !== null && (
          <>
            <p role="alert" className="text-destructive text-sm">
              {refused}
            </p>
            <Button
              variant="outline"
              disabled={sessions.estimate.isPending}
              onClick={() =>
                void act(async () => {
                  const priced = await sessions.estimate.mutateAsync(body);
                  setRefusal(null);
                  setQuote({ key: asked, value: priced });
                  setBudget(priced.total_usd);
                })
              }
            >
              {t("estimate")}
            </Button>
          </>
        )}
        {target && !quote && refused === null && <p role="status">{t("estimating")}</p>}
        {quote && (
          <section className="space-y-3 rounded-lg border p-4">
            <p>
              {t("sessionQuote", {
                minutes: quote.estimated_minutes,
                cost: usd(quote.total_usd, locale),
                count: quote.cases,
                rounds: quote.max_iterations,
              })}
            </p>
            <p className="text-muted-foreground text-sm">
              {t("evidence", { count: quote.evidence_runs })}
            </p>
            {Number(quote.knowledge_usd ?? 0) > 0 && (
              <p className="text-muted-foreground text-sm">
                {t("knowledgeEstimate", { cost: usd(quote.knowledge_usd ?? "0", locale) })}
              </p>
            )}
            {quote.reason && <p role="status">{tr(`reason.${quote.reason}`)}</p>}
            <Label htmlFor="improvement-budget">{t("budget")}</Label>
            <Input
              id="improvement-budget"
              type="number"
              min="0.000001"
              step="0.01"
              value={budget}
              onChange={(e) => setBudget(e.target.value)}
            />
            <Button
              disabled={
                !quote.affordable ||
                quote.reason !== null ||
                !Number.isFinite(Number(budget)) ||
                Number(budget) <= 0 ||
                sessions.start.isPending
              }
              onClick={() =>
                void act(async () => {
                  const started = await sessions.start.mutateAsync({ ...body, budget_usd: budget });
                  if (useOrgStore.getState().activeOrgId === organizationId)
                    router.push(`/agents/${agentId}/improve/${started.id}`);
                })
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
      </div>
      {baseline && (
        <StartEvalDialog agentId={agentId} datasetId={target} onOpenChange={setBaseline} />
      )}
    </div>
  );
}
