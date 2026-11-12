"use client";

import Link from "next/link";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui";
import { usePermissions } from "@/hooks/use-permissions";
import { useSkillTestSet } from "@/hooks/use-skill-check";
import { ApiError, getErrorMessage } from "@/lib/api-error";
import { ROUTES } from "@/lib/constants";
import { Perm } from "@/types/permissions";

/**
 * The skill's own test questions, which let an agent with none of its own be
 * checked at all: a link when they exist, and the way to write them when not.
 */
export function AddTestQuestions({
  skillId,
  onCreated,
}: {
  skillId: string;
  /** Called once the questions are written, for a price that counted none to be read again. */
  onCreated?: () => void;
}) {
  const t = useTranslations("skillImprovement.testSet");
  const tErrors = useTranslations("errors");
  const { can } = usePermissions();
  const { testSet, isLoading, error, create } = useSkillTestSet(skillId);
  if (isLoading) return null;
  if (error) return <p className="text-destructive text-sm">{getErrorMessage(error, tErrors)}</p>;
  if (testSet) {
    return (
      <p className="text-sm">
        <Link className="underline underline-offset-4" href={ROUTES.DATASET_DETAIL(testSet.id)}>
          {t("has", { count: testSet.case_count })}
        </Link>
      </p>
    );
  }
  if (!can(Perm.datasetsEdit)) return null;
  const refused =
    create.error && !(create.error instanceof ApiError && create.error.status === 409)
      ? getErrorMessage(create.error, tErrors)
      : null;
  return (
    <div className="space-y-1">
      <Button
        variant="outline"
        size="sm"
        data-tour="skill-improvement-test-set"
        loading={create.isPending}
        onClick={() => create.mutate(undefined, { onSuccess: onCreated })}
      >
        {t("add")}
      </Button>
      <p className="text-muted-foreground text-xs">{t("addHint")}</p>
      {refused !== null && (
        <p role="alert" className="text-destructive text-sm">
          {refused}
        </p>
      )}
    </div>
  );
}
