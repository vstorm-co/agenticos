"use client";

import { useLocale, useTranslations } from "next-intl";

import type { SkillImprovementForked } from "@/types/skill-improvement";

/**
 * What forking a session's change did. An agent publishing for itself moved at once;
 * one the reader may only change in its draft moved there, and reads main until the
 * draft is published - which the person has to know to finish it.
 */
export function ForkedSummary({ forked }: { forked: SkillImprovementForked }) {
  const t = useTranslations("skillImprovement.forked");
  const list = new Intl.ListFormat(useLocale(), { type: "conjunction" });
  const names = (rows: { name: string }[]) => list.format(rows.map((row) => row.name));
  return (
    <section
      role="status"
      aria-label={t("title")}
      className="space-y-1.5 rounded-lg border p-3 text-sm"
    >
      <p>{t("made", { name: forked.fork.name })}</p>
      {forked.moved.length > 0 && (
        <p>{t("live", { count: forked.moved.length, names: names(forked.moved) })}</p>
      )}
      {forked.draft_only.length > 0 && (
        <p>{t("drafts", { count: forked.draft_only.length, names: names(forked.draft_only) })}</p>
      )}
      {forked.moved.length + forked.draft_only.length === 0 && <p>{t("nobody")}</p>}
    </section>
  );
}
