"use client";

import { useEffect, useRef } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";

import { ErrorState } from "@/components/states";
import { AddTestQuestions } from "@/components/skill-improvement/add-test-questions";
import { ListCard, Skeleton } from "@/components/ui";
import { useSkillTestSet } from "@/hooks/use-skill-check";
import { ApiError, getErrorMessage } from "@/lib/api-error";
import { ROUTES } from "@/lib/constants";

/** The page's anchor for this section, which a check that found nothing to ask links to. */
export const TEST_QUESTIONS_ANCHOR = "test-questions";

/**
 * The skill's own test questions: every agent using the skill is asked them when a
 * change to it is checked, so an agent with no questions of its own can be checked
 * too. A link to the dataset once they exist; otherwise the ways to start them -
 * the same control the check dialog offers - to whoever may write them.
 */
export function SkillTestQuestions({
  skillId,
  canCreate,
}: {
  skillId: string;
  /** The reader may edit the skill and create datasets, which writing them needs. */
  canCreate: boolean;
}) {
  const t = useTranslations("skills.page.testQuestions");
  const tErrors = useTranslations("errors");
  const { testSet, isLoading, error } = useSkillTestSet(skillId);
  const card = useRef<HTMLDivElement>(null);
  // The section draws once its read answers, after the browser has looked for the hash.
  useEffect(() => {
    if (!isLoading && window.location.hash === `#${TEST_QUESTIONS_ANCHOR}`) {
      card.current?.scrollIntoView({ block: "start" });
    }
  }, [isLoading]);

  return (
    <ListCard
      ref={card}
      id={TEST_QUESTIONS_ANCHOR}
      className="scroll-mt-20"
      title={t("title")}
      counted={isLoading ? null : t("count", { count: testSet?.case_count ?? 0 })}
      headerTour="skill-test-questions"
    >
      {error instanceof ApiError && error.details?.reason === "test_set_hidden" ? (
        <p className="text-muted-foreground text-sm">{t("hidden")}</p>
      ) : error ? (
        <ErrorState description={getErrorMessage(error, tErrors)} />
      ) : isLoading ? (
        <Skeleton className="h-10 w-full" />
      ) : testSet ? (
        <div className="space-y-2 text-sm">
          <p className="text-muted-foreground">{t("body")}</p>
          <Link
            className="font-medium underline underline-offset-4"
            href={ROUTES.DATASET_DETAIL(testSet.id)}
          >
            {t("open", { name: testSet.name })}
          </Link>
        </div>
      ) : (
        <div className="space-y-3 text-sm">
          <p className="text-muted-foreground">{t("none")}</p>
          {canCreate ? (
            <AddTestQuestions skillId={skillId} />
          ) : (
            <p className="text-muted-foreground">{t("askEditor")}</p>
          )}
        </div>
      )}
    </ListCard>
  );
}
