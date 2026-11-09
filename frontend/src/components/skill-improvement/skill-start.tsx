"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useLocale, useTranslations } from "next-intl";

import { limitText, limitValue, sessionLimit, usd } from "@/components/evals/format";
import { EvidenceOnly, evidenceOnlyDataset } from "@/components/improvement/evidence-only";
import { ErrorState, LoadingState } from "@/components/states";
import { Button, Input, Label } from "@/components/ui";
import { useSkillImprovements } from "@/hooks/use-skill-improvement";
import { getErrorMessage } from "@/lib/api-error";
import { ROUTES } from "@/lib/constants";
import { openImprovement } from "@/lib/improvement-steps";
import type { SkillImprovementEstimate } from "@/types/skill-improvement";

/**
 * Starting a session on one line of the skill: which agents it will be checked on,
 * the ones that cannot be, named before anything is spent, and what it costs.
 */
export function SkillStart({
  skillId,
  forkId,
  fromRun = null,
}: {
  skillId: string;
  forkId: string | null;
  /** An agent's session that handed its problems with this skill over. */
  fromRun?: string | null;
}) {
  const t = useTranslations("skillImprovement.start");
  const tErrors = useTranslations("errors");
  const locale = useLocale();
  const router = useRouter();
  const { sessions, isLoading, error, estimate, start } = useSkillImprovements(skillId, {
    forkId,
    fromRun,
  });
  const [quote, setQuote] = useState<SkillImprovementEstimate | null>(null);
  const [limit, setLimit] = useState("");
  const [refusal, setRefusal] = useState<string | null>(null);
  const [evidence, setEvidence] = useState<string | null>(null);
  const open = openImprovement(sessions);
  const { mutateAsync: price } = estimate;

  // Priced only once the line's sessions are read: an open one is continued, not priced.
  useEffect(() => {
    if (isLoading || error || open) return;
    price()
      .then((value) => {
        setQuote(value);
        setLimit(limitText(sessionLimit(value), locale));
      })
      .catch((failure: unknown) => {
        setEvidence(evidenceOnlyDataset(failure));
        setRefusal(getErrorMessage(failure, tErrors));
      });
  }, [isLoading, error, open, price, locale, tErrors]);

  if (isLoading) return <LoadingState variant="skeleton-cards" rows={2} />;
  if (error) return <ErrorState description={getErrorMessage(error, tErrors)} />;
  if (open) {
    return (
      <p className="text-sm">
        {t("openSession")}{" "}
        <Link
          className="underline underline-offset-4"
          href={`${ROUTES.SKILL_DETAIL(skillId)}/improve/${open.id}`}
        >
          {t("continue")}
        </Link>
      </p>
    );
  }
  if (evidence !== null && quote === null) return <EvidenceOnly datasetId={evidence} />;
  if (refusal !== null && quote === null) return <ErrorState description={refusal} />;
  if (quote === null) return <LoadingState variant="skeleton-cards" rows={2} />;

  const typed = Number(limitValue(limit));

  async function begin() {
    setRefusal(null);
    try {
      const session = await start.mutateAsync(limitValue(limit));
      router.push(`${ROUTES.SKILL_DETAIL(skillId)}/improve/${session.id}`);
    } catch (failure) {
      setRefusal(getErrorMessage(failure, tErrors));
    }
  }
  return (
    <section className="space-y-5 rounded-xl border p-6" data-tour="skill-improvement-start">
      <h2 className="font-medium">{t("title")}</h2>
      {quote.reason === "no_evidence" ? (
        <p role="alert" className="text-sm">
          {t("noEvidence")}
        </p>
      ) : (
        <p className="text-sm">{t("reads", { runs: quote.evidence_runs, agents: quote.agents })}</p>
      )}
      {quote.hidden_agents > 0 && (
        <p className="text-muted-foreground text-xs">
          {t("hidden", { count: quote.hidden_agents })}
        </p>
      )}
      {quote.usage_unknown > 0 && (
        <p className="text-muted-foreground text-xs">
          {t("usageUnknown", { count: quote.usage_unknown })}
        </p>
      )}
      <p className="text-muted-foreground text-xs">{t("checkNamedLater")}</p>
      <p className="text-sm">
        {t("price", {
          cost: usd(quote.total_usd, locale),
          perRound: usd(quote.per_round_usd, locale),
          rounds: quote.max_iterations,
          limit: usd(typed > 0 ? String(typed) : sessionLimit(quote), locale),
        })}
      </p>
      <div className="max-w-xs space-y-1.5">
        <Label htmlFor="skill-improvement-limit">{t("limit")}</Label>
        <Input
          id="skill-improvement-limit"
          inputMode="decimal"
          value={limit}
          onChange={(event) => setLimit(event.target.value)}
        />
        <p className="text-muted-foreground text-xs">{t("limitHint")}</p>
      </div>
      {!quote.affordable && quote.reason === null && (
        <p role="alert" className="text-sm">
          {t("unaffordable")}
        </p>
      )}
      {refusal !== null && (
        <p role="alert" className="text-destructive text-sm">
          {refusal}
        </p>
      )}
      <Button
        disabled={!quote.affordable || quote.reason !== null || !(typed > 0)}
        loading={start.isPending}
        onClick={() => void begin()}
      >
        {t("start")}
      </Button>
    </section>
  );
}
