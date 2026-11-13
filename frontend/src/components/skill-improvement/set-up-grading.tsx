"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";

import { ROUTES } from "@/lib/constants";
import type { SkillCheckAgent } from "@/types/skill-checks";

/**
 * Where to give questions nothing could grade a way to be graded: the Grading tab
 * of each dataset these agents were to be asked, once each. A dataset the reader
 * may not see has no name, and no link.
 */
export function SetUpGrading({ agents }: { agents: SkillCheckAgent[] }) {
  const t = useTranslations("skillImprovement.testSet");
  const datasets = new Map<string, string>();
  for (const stage of agents.flatMap((row) => row.stages)) {
    if (stage.dataset_name !== null) datasets.set(stage.dataset_id, stage.dataset_name);
  }
  if (datasets.size === 0) return null;
  return (
    <ul className="space-y-0.5 text-sm">
      {[...datasets].map(([id, name]) => (
        <li key={id}>
          <Link
            className="underline underline-offset-4"
            href={`${ROUTES.DATASET_DETAIL(id)}?tab=grading`}
          >
            {t("grading", { name })}
          </Link>
        </li>
      ))}
    </ul>
  );
}
