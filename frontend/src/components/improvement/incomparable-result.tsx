"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";

export function IncomparableResult({
  agentId,
  runId,
  reason,
}: {
  agentId: string;
  runId: string;
  reason: string | null;
}) {
  const t = useTranslations("improvement");
  return (
    <div className="space-y-2 rounded-lg border p-3 text-sm">
      <p role="alert" className="font-medium">
        {t("comparisonInvalid")}
      </p>
      {reason && <p className="text-muted-foreground">{reason}</p>}
      <Link className="underline underline-offset-4" href={`/agents/${agentId}/evals/${runId}`}>
        {t("openCheck")}
      </Link>
    </div>
  );
}
