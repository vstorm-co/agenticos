"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui";
import { ApiError } from "@/lib/api-error";
import { ROUTES } from "@/lib/constants";

/**
 * The dataset a check was refused on because every question in it was taken from the
 * conversations the change learned from, or null for any other refusal.
 */
export function evidenceOnlyDataset(error: unknown): string | null {
  if (!(error instanceof ApiError) || error.details?.reason !== "all_evidence") {
    return null;
  }
  const id = error.details.dataset_id;
  return typeof id === "string" ? id : null;
}

/**
 * Why no question of a dataset can test the change, and where to add ones that can.
 * Nothing else is offered: which datasets a check asks comes from the line's agents.
 */
export function EvidenceOnly({ datasetId }: { datasetId: string }) {
  const t = useTranslations("improvement.evidenceOnly");
  return (
    <div role="alert" className="border-destructive/30 space-y-3 rounded-xl border p-4">
      <p className="text-sm">{t("body")}</p>
      <Button asChild variant="outline" size="sm">
        <Link href={ROUTES.DATASET_DETAIL(datasetId)}>{t("addQuestions")}</Link>
      </Button>
    </div>
  );
}
