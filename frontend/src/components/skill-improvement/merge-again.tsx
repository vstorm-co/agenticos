"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";

import { ROUTES } from "@/lib/constants";
import type { SkillImprovement } from "@/types/skill-improvement";

/**
 * In place of Check again, for a catch-up or a move to main whose lines moved on: a merge
 * is of the versions it read, so it is checked once, and the newer version is taken in by
 * starting the merge again.
 */
export function MergeAgain({ session }: { session: SkillImprovement }) {
  const t = useTranslations("skillImprovement.mergeAgain");
  const fork = session.purpose === "catch_up" ? session.fork_id : session.source_fork_id;
  return (
    <p role="status" className="text-sm">
      {t("moved")}{" "}
      <Link
        className="underline underline-offset-4"
        href={`${ROUTES.SKILL_DETAIL(session.skill_id)}/improve/new?fork=${fork}&merge=${session.purpose}`}
      >
        {t("start")}
      </Link>
    </p>
  );
}
