"use client";

import { useTranslations } from "next-intl";

import type { CaseScore } from "@/types/scoring";

/**
 * Where an answer came from: a side of a skill's check, an eval run or grading by
 * hand, and which re-ask it was. One question answered many times reads as many
 * rows, and this is what tells them apart.
 */
export function ScoreOrigin({ score }: { score: CaseScore }) {
  const t = useTranslations("datasets.scoring.origin");
  const check = score.skill_check;
  const source = check
    ? t("check", {
        arm: check.arm,
        known: check.version === null ? "no" : "yes",
        version: check.version ?? 0,
      })
    : score.eval_run_id !== null
      ? t("eval")
      : t("hand");
  const attempt = score.eval_attempt ?? 0;
  return (
    <span className="text-muted-foreground text-xs font-normal">
      {attempt > 0 ? t("rerun", { source, attempt }) : source}
    </span>
  );
}
