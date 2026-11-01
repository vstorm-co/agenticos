"use client";

import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import { Button } from "@/components/ui/button";
import { usePromotionGate } from "@/hooks/use-promotion-gate";
import { ROUTES } from "@/lib/constants";
import { resultReasons } from "@/components/evals/suites/suite-format";
import { ReviewReevaluationNote } from "@/components/evals/review-reevaluation-note";

export function EnvironmentGuardStatus({
  agentId,
  environmentId,
  versionId,
  version,
  servedVersion,
  canReadRuns,
  onPromote,
}: {
  agentId: string;
  environmentId: string;
  versionId: string;
  version: number;
  servedVersion: number;
  canReadRuns: boolean;
  onPromote: () => void;
}) {
  const t = useTranslations("promotionGate");
  const ts = useTranslations("evals.suites");
  const locale = useLocale();
  const { gate, error } = usePromotionGate(agentId, environmentId, versionId, {
    enabled: canReadRuns,
  });
  if (!canReadRuns)
    return (
      <span className="inline-flex flex-wrap items-center gap-2">
        {t("staysOn", { version: servedVersion })}
        <Button size="sm" variant="link" className="h-auto px-0" onClick={onPromote}>
          {t("reviewPromotion")}
        </Button>
      </span>
    );
  if (error)
    return (
      <Button size="sm" variant="link" onClick={onPromote}>
        {t("readStatus")}
      </Button>
    );
  if (!gate) return <span role="status">{t("loading")}</span>;
  return (
    <div className="basis-full space-y-1 text-xs">
      <p>
        {t(gate.passing ? "readyToPromote" : "staysOn", {
          version: gate.passing ? version : servedVersion,
        })}
      </p>
      {gate.guards.map((guard) => (
        <div key={guard.suite_id} className="space-y-1">
          <span className={guard.state === "failed" ? "text-destructive" : "text-muted-foreground"}>
            {t("guardStatus", { name: guard.suite_name, status: t(`state.${guard.state}`) })}
          </span>
          {guard.result && (
            <>
              {resultReasons(guard.result, ts, locale).map((reason) => (
                <p key={reason}>{reason}</p>
              ))}
              {guard.result.summary?.review && (
                <ReviewReevaluationNote review={guard.result.summary.review} />
              )}
              {guard.result.eval_run_id && (
                <Link
                  className="underline underline-offset-4"
                  href={`${ROUTES.AGENTS}/${agentId}/evals/${guard.result.eval_run_id}`}
                >
                  {t("openRun")}
                </Link>
              )}
            </>
          )}
        </div>
      ))}
      <Button size="sm" variant="link" className="h-auto px-0" onClick={onPromote}>
        {t("reviewPromotion")}
      </Button>
    </div>
  );
}
