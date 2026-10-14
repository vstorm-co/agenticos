"use client";

import { useLocale, useTranslations } from "next-intl";

import { Badge } from "@/components/ui";
import type { CallOutcome, EvalAttempt, EvalRunArm } from "@/types/eval-runs";
import { seconds, usd } from "./format";

const CALL_TONE: Record<CallOutcome, "secondary" | "warning" | "outline"> = {
  executed: "secondary",
  replayed: "outline",
  blocked: "warning",
  divergent: "warning",
};

function Attempt({ attempt }: { attempt: EvalAttempt }) {
  const t = useTranslations("evals.case");
  const locale = useLocale();
  return (
    <div className="space-y-2 rounded-md border p-3">
      <p className="text-muted-foreground flex flex-wrap gap-x-3 text-xs">
        <span>{attempt.attempt === 0 ? t("firstAnswer") : t("rerun", { n: attempt.attempt })}</span>
        <span>{t(`outcome.${String(attempt.outcome)}`)}</span>
        <span>{usd(attempt.cost_usd, locale)}</span>
        <span>{seconds(attempt.latency_ms, locale)}</span>
      </p>
      {attempt.answer !== null && (
        <p className="text-foreground text-sm whitespace-pre-wrap">{attempt.answer}</p>
      )}
      {attempt.error && <p className="text-destructive text-xs">{attempt.error}</p>}
      {attempt.calls.length > 0 && (
        <ul className="space-y-1">
          {attempt.calls.map((call, index) => (
            <li key={index} className="flex flex-wrap items-center gap-2 text-xs">
              <Badge variant={CALL_TONE[call.outcome]}>{t(`call.${call.outcome}`)}</Badge>
              <code className="break-all">
                {call.tool}({JSON.stringify(call.args)})
              </code>
            </li>
          ))}
        </ul>
      )}
      {attempt.score && (
        <ul className="space-y-0.5 text-xs">
          {attempt.score.results.map((result, index) => (
            <li key={index}>
              <span className="font-medium">{result.name}</span> · {t(`scorer.${result.status}`)} ·{" "}
              <span className="text-muted-foreground">{result.reason}</span>
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}

/**
 * One case answered by every arm of the run, side by side - the candidate
 * beside the baseline when one ran here - with each answer, its calls and
 * what every scorer said.
 */
export function CaseDetail({ attempts, arms }: { attempts: EvalAttempt[]; arms: EvalRunArm[] }) {
  const t = useTranslations("evals.arms");
  return (
    <div className="grid gap-3 md:grid-cols-2">
      {arms.map((arm) => {
        const own = attempts.filter((attempt) => attempt.arm_id === arm.id);
        return (
          <div key={arm.id} className="space-y-2">
            <p className="text-muted-foreground text-xs font-medium">
              {t(`role.${arm.role}`, { model: arm.model_label })}
            </p>
            {own.map((attempt) => (
              <Attempt key={attempt.id} attempt={attempt} />
            ))}
          </div>
        );
      })}
    </div>
  );
}
