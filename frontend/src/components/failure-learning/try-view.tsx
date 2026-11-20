"use client";

import { useTranslations } from "next-intl";

import { Badge, Card, CardContent } from "@/components/ui";
import type { EvalTryCaseRead, EvalTryRead } from "@/lib/failure-learning-api";

function CaseVerdict({ result }: { result: EvalTryCaseRead }) {
  const t = useTranslations("failureLearning");
  // Old passes and new passes is exactly "the case does not reproduce":
  // the gate needs old to fail and new to pass, so the verdict is read off
  // the two sides rather than matched on the API's English reason string.
  const doesNotReproduce = result.old_passed === true && result.new_passed === true;
  return (
    <Card>
      <CardContent className="space-y-1 p-4">
        <div className="flex flex-wrap items-center gap-2">
          <p className="font-medium">{result.name}</p>
          <Badge variant={result.gate_passed === true ? "default" : "secondary"}>
            {result.status === "pending"
              ? t("gatePending")
              : result.gate_passed
                ? t("gatePassed")
                : t("gateFailed")}
          </Badge>
        </div>
        <p className="text-muted-foreground text-sm">
          {result.old_passed === null
            ? t("gatePending")
            : result.old_passed
              ? t("oldPassed")
              : t("oldFailed")}
          {" · "}
          {result.new_passed === null
            ? t("gatePending")
            : result.new_passed
              ? t("newPassed")
              : t("newFailed")}
        </p>
        {doesNotReproduce && <p className="text-sm">{t("doesNotReproduce")}</p>}
        {!doesNotReproduce && result.reason && <p className="text-sm">{result.reason}</p>}
      </CardContent>
    </Card>
  );
}

/**
 * One try, judged as its runs stand now: a run still going leaves its case
 * pending, and a case whose old side already passes does not reproduce the
 * failure - the case is wrong, not the instruction.
 */
export function TryView({ evaluation }: { evaluation: EvalTryRead }) {
  const t = useTranslations("failureLearning");
  return (
    <div className="space-y-3">
      {evaluation.pending > 0 && <p className="text-muted-foreground text-sm">{t("tryRunning")}</p>}
      {evaluation.cases.map((result) => (
        <CaseVerdict key={result.eval_id} result={result} />
      ))}
    </div>
  );
}
