"use client";

import { useLocale, useTranslations } from "next-intl";
import type { ReviewReevaluation } from "@/types/scoring";
import { formatDateTime } from "@/lib/utils";

export function ReviewReevaluationNote({ review }: { review: ReviewReevaluation }) {
  const t = useTranslations("evals.reviewReevaluation");
  const locale = useLocale();
  return (
    <p className="text-muted-foreground text-xs">
      {t(review.undo ? "undone" : "by", {
        name: review.by_name ?? t("reviewer"),
        date: formatDateTime(review.at, locale),
      })}
    </p>
  );
}
