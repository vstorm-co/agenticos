"use client";

import { MonetaryInput } from "@/components/money/monetary-input";
import { useMonetaryInputs } from "@/hooks/use-monetary-inputs";
import { useMoney } from "@/components/providers/currency-provider";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useConsoleRouter as useRouter } from "@/hooks/use-console-router";
import { useLocale, useTranslations } from "next-intl";

import { limitValue } from "@/components/evals/format";
import { ErrorState, LoadingState } from "@/components/states";
import { Button, Label } from "@/components/ui";
import { useSkillImprovements } from "@/hooks/use-skill-improvement";
import { useSkillMergeStart } from "@/hooks/use-skill-merge";
import { getErrorMessage } from "@/lib/api-error";
import { ROUTES } from "@/lib/constants";
import { openImprovement } from "@/lib/improvement-steps";
import type { MergeKind, SkillMergeEstimate } from "@/types/skill-merge";

/**
 * Starting a catch-up of a fork with main, or a move of a fork to main: what the merge
 * would take in, how many parts conflict, and what proposing their texts costs. The
 * check is priced at Changes, once the merge is settled.
 */
export function MergeStart({
  skillId,
  forkId,
  kind,
}: {
  skillId: string;
  forkId: string;
  kind: MergeKind;
}) {
  const monetary = useMonetaryInputs();
  const money = useMoney();
  const tm = useTranslations("currencies");
  const t = useTranslations("skillImprovement.mergeStart");
  const tErrors = useTranslations("errors");
  const locale = useLocale();
  const router = useRouter();
  // A catch-up is a session on the fork, a move to main one on main: one open per line.
  const line = useSkillImprovements(skillId, {
    forkId: kind === "catch_up" ? forkId : null,
    fromRun: null,
  });
  const { estimate, start } = useSkillMergeStart(skillId, forkId, kind);
  const [quote, setQuote] = useState<SkillMergeEstimate | null>(null);
  const [limit, setLimit] = useState("");
  const [refusal, setRefusal] = useState<string | null>(null);
  const open = openImprovement(line.sessions);
  const { mutateAsync: price } = estimate;

  useEffect(() => {
    if (line.isLoading || line.error || open) return;
    price()
      .then((value) => {
        setQuote(value);
        setLimit(value.total_usd);
      })
      .catch((failure: unknown) => setRefusal(getErrorMessage(failure, tErrors)));
  }, [line.isLoading, line.error, open, price, locale, tErrors]);

  if (line.isLoading) return <LoadingState variant="pending" />;
  if (line.error) return <ErrorState description={getErrorMessage(line.error, tErrors)} />;
  if (open)
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
  if (refusal !== null && quote === null) return <ErrorState description={refusal} />;
  if (quote === null) return <LoadingState variant="pending" />;

  async function begin() {
    setRefusal(null);
    try {
      const session = await start.mutateAsync(monetary.payload({ budget_usd: limitValue(limit) }));
      router.push(`${ROUTES.SKILL_DETAIL(skillId)}/improve/${session.id}`);
    } catch (failure) {
      setRefusal(getErrorMessage(failure, tErrors));
    }
  }
  // A catch-up runs on the fork itself; a move to main names the fork it takes from.
  const fork = (quote.source_fork ?? quote.line).name;
  return (
    <section className="space-y-5 rounded-xl border p-6" data-tour="skill-merge-start">
      <h2 className="font-medium">{t(`title.${kind}`, { fork })}</h2>
      <p className="text-sm">{t(`what.${kind}`, { fork, version: quote.base_version.number })}</p>
      <p className="text-sm">{t("conflicts", { count: quote.conflicts })}</p>
      <p className="text-sm">{t("agents", { count: quote.agents })}</p>
      {quote.hidden_agents > 0 && (
        <p className="text-muted-foreground text-xs">
          {t("hidden", { count: quote.hidden_agents })}
        </p>
      )}
      <p className="text-sm">{t("price", { cost: money.cost(quote.total_usd, locale) })}</p>
      <div className="max-w-xs space-y-1.5">
        <Label htmlFor="skill-merge-limit">
          {tm("budgetLabel", { currency: money.currency ?? "—" })}
        </Label>
        <MonetaryInput
          id="skill-merge-limit"
          monetary={monetary}
          field="budget_usd"
          value={limit}
          onValueChange={setLimit}
        />
        <p className="text-muted-foreground text-xs">{t("limitHint")}</p>
      </div>
      {!quote.affordable && (
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
        disabled={!quote.affordable || !(Number(limitValue(limit)) >= 0) || limit.trim() === ""}
        loading={start.isPending}
        onClick={() => void begin()}
      >
        {t(`start.${kind}`)}
      </Button>
    </section>
  );
}
