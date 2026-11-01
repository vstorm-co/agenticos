"use client";

import { useEffect, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { Button } from "@/components/ui";
import { usd } from "@/components/evals/format";
import { useAgentTestSet } from "@/hooks/use-agent-test-set";
import { useCaseGenerations } from "@/hooks/use-case-generation";
import { getErrorMessage } from "@/lib/api-error";
import type { AgentTestSetBootstrap, AgentTestSetEstimate } from "@/types/agent-test-set";

const JUDGE_REASONS = ["one_model", "ai_off", "cannot_publish", "unknown_model", "shares_model"];

/**
 * Writes the agent's test questions inside the wizard: its rated answers become
 * questions and the generator adds more, which join the test set as they are
 * written. `onReady` hears the test set once nothing is still being written.
 */
export function WriteQuestions({
  agentId,
  more,
  onReady,
}: {
  agentId: string;
  more?: number;
  onReady: (datasetId: string) => void;
}) {
  const t = useTranslations("improvement");
  const tErrors = useTranslations("errors");
  const locale = useLocale();
  const testSet = useAgentTestSet(agentId);
  const [quote, setQuote] = useState<AgentTestSetEstimate | null>(null);
  const [built, setBuilt] = useState<AgentTestSetBootstrap | null>(null);
  const [error, setError] = useState<string | null>(null);
  const priceWriting = testSet.estimate.mutateAsync;
  useEffect(() => {
    let current = true;
    priceWriting(more ? { more } : {}).then(
      (priced) => {
        if (current) setQuote(priced);
      },
      (failure: unknown) => {
        if (current) setError(getErrorMessage(failure, tErrors));
      },
    );
    return () => {
      current = false;
    };
  }, [more, priceWriting, tErrors]);
  if (built) return <Written built={built} onReady={onReady} />;
  return (
    <section className="space-y-3 rounded-lg border p-4" data-tour="improvement-write-questions">
      <p className="text-sm">{t("writeQuestionsBody")}</p>
      {quote ? (
        <p className="text-sm">
          {quote.priced
            ? t("writeQuestionsQuote", { count: quote.generate, cost: usd(quote.cost_usd, locale) })
            : t("writeQuestionsUnpriced")}
        </p>
      ) : (
        !error && <p role="status">{t("estimating")}</p>
      )}
      <Button
        disabled={!quote?.priced || testSet.build.isPending}
        onClick={() =>
          void (async () => {
            setError(null);
            try {
              setBuilt(await testSet.build.mutateAsync(more ? { more } : {}));
            } catch (failure) {
              setError(getErrorMessage(failure, tErrors));
            }
          })()
        }
      >
        {more ? t("writeMoreQuestions", { count: more }) : t("writeQuestions")}
      </Button>
      {error && (
        <p role="alert" className="text-destructive text-sm">
          {error}
        </p>
      )}
    </section>
  );
}

function Written({
  built,
  onReady,
}: {
  built: AgentTestSetBootstrap;
  onReady: (datasetId: string) => void;
}) {
  const t = useTranslations("improvement");
  const { generations } = useCaseGenerations(built.dataset_id, {
    enabled: built.generation_id !== null,
  });
  const generation = generations.find((item) => item.id === built.generation_id);
  const writing = built.generation_id !== null && (!generation || generation.status === "running");
  useEffect(() => {
    if (!writing) onReady(built.dataset_id);
  }, [writing, built.dataset_id, onReady]);
  return (
    <section className="space-y-2 rounded-lg border p-4 text-sm" role="status">
      <p>
        {t("writtenCounts", {
          down: built.counts.rated_bad,
          liked: built.counts.rated_good,
          written: built.counts.generated_requested,
        })}
      </p>
      {writing ? (
        <p>{t("questionsWriting")}</p>
      ) : generation?.status === "failed" ? (
        <p className="text-warning">{t("questionsWritingFailed")}</p>
      ) : (
        <p>{t("questionsWritten")}</p>
      )}
      {built.generation_skipped && <p>{t(`generationSkipped.${built.generation_skipped}`)}</p>}
      {built.too_few && <p className="text-warning">{t("tooFewQuestions")}</p>}
      {built.judge.reason_code && JUDGE_REASONS.includes(built.judge.reason_code) && (
        <p className="text-muted-foreground">{t(`graderReason.${built.judge.reason_code}`)}</p>
      )}
    </section>
  );
}
