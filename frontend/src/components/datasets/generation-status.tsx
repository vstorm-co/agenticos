"use client";

import Link from "next/link";
import { AlertTriangle, Loader2 } from "lucide-react";
import { useTranslations } from "next-intl";

import { ROUTES } from "@/lib/constants";
import type { CaseGeneration } from "@/types/case-generation";

/**
 * How the newest generation is going, when there is something to say.
 *
 * A finished one says nothing here - its drafts are the list below. A running
 * one and a failed one each say so, with the generator's run one click away:
 * that is where its cost and its transcript are.
 */
export function GenerationStatus({ generation }: { generation: CaseGeneration | undefined }) {
  const t = useTranslations("datasets");
  if (generation === undefined || generation.status === "ready") return null;
  const run =
    generation.run_id !== null ? (
      <Link className="underline" href={`${ROUTES.RUNS}?run=${generation.run_id}`}>
        {t("generatorRun")}
      </Link>
    ) : null;
  if (generation.status === "running") {
    return (
      <p className="text-muted-foreground flex items-center gap-2 text-sm" role="status">
        <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
        {t("generating", { count: generation.requested_count })}
      </p>
    );
  }
  return (
    <p className="text-destructive flex flex-wrap items-center gap-2 text-sm" role="alert">
      <AlertTriangle className="h-4 w-4" aria-hidden />
      {generation.error ?? t("generationFailed")}
      {run}
    </p>
  );
}
