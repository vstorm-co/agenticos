"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui";
import { useImprovement } from "@/hooks/use-improvements";
import { getErrorMessage } from "@/lib/api-error";
import { ROUTES } from "@/lib/constants";
import { subjectOf } from "@/lib/improvement-subject";
import type { SkillImprovement } from "@/types/skill-improvement";

/**
 * In place of Check again, for a catch-up or a move to main whose lines moved on: a merge
 * is of the versions it read, so it is checked once, and the newer version is taken in by
 * a new merge. This session is still the line's open one, which a new start would only
 * lead back to, so it is discarded first.
 */
export function MergeAgain({ session }: { session: SkillImprovement }) {
  const t = useTranslations("skillImprovement.mergeAgain");
  const tErrors = useTranslations("errors");
  const router = useRouter();
  const actions = useImprovement(subjectOf(session), session.id);
  const [error, setError] = useState<string | null>(null);
  const fork = session.purpose === "catch_up" ? session.fork_id : session.source_fork_id;
  async function again() {
    setError(null);
    try {
      await actions.discard.mutateAsync();
      router.push(
        `${ROUTES.SKILL_DETAIL(session.skill_id)}/improve/new?fork=${fork}&merge=${session.purpose}`,
      );
    } catch (failure) {
      setError(getErrorMessage(failure, tErrors));
    }
  }
  return (
    <div className="space-y-2">
      <p role="status" className="text-sm">
        {t("moved")}
      </p>
      {session.can_discard !== false && (
        <Button variant="outline" loading={actions.discard.isPending} onClick={() => void again()}>
          {t("start")}
        </Button>
      )}
      {error !== null && (
        <p role="alert" className="text-destructive text-sm">
          {error}
        </p>
      )}
    </div>
  );
}
