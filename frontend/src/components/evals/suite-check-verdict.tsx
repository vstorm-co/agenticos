"use client";

import type { ReactNode } from "react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";

import { Badge } from "@/components/ui";
import { ROUTES } from "@/lib/constants";
import type { EvalSuiteCheck } from "@/types/eval-runs";
import { RESULT_TONE, reasonText } from "./suites/suite-format";

/**
 * What the suite a check ran on would have said, worded as the suite's own results
 * are. Nothing until the run completes; the suite's name links to the agent's suites
 * only while that suite is still there.
 */
export function SuiteCheckVerdict({ agentId, check }: { agentId: string; check: EvalSuiteCheck }) {
  const t = useTranslations("evals.suites");
  const locale = useLocale();
  if (check.status === null) return null;
  const suite = (chunks: ReactNode) =>
    check.suite_exists ? (
      <Link href={`${ROUTES.AGENTS}/${agentId}?tab=evals`} className="underline">
        {chunks}
      </Link>
    ) : (
      <span>{chunks}</span>
    );
  return (
    <div className="space-y-1 text-sm">
      <p className="flex flex-wrap items-center gap-2">
        <Badge variant={RESULT_TONE[check.status]}>{t(`status.${check.status}`)}</Badge>
        <span className="text-muted-foreground">
          {t.rich("checkVerdict", { name: check.name, suite })}
        </span>
      </p>
      {check.reasons.length > 0 && (
        <ul className="text-muted-foreground list-disc pl-5 text-xs">
          {check.reasons.map((reason) => (
            <li key={reason.code}>{reasonText(reason, t, locale)}</li>
          ))}
        </ul>
      )}
    </div>
  );
}
