"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { ReturnedSummary } from "@/components/skill-improvement/returned-summary";
import { ConfirmDialog } from "@/components/ui";
import { useReturnForkToMain } from "@/hooks/use-skill-merge";
import { getErrorMessage } from "@/lib/api-error";
import type { ReturnedToMain } from "@/types/skill-merge";
import type { SkillFork } from "@/types/skill-versions";

/**
 * Moves a fork's agents back to main's newest version. A fork with no version of its own
 * has nothing to catch up or move to main, so this is how its agents follow main again.
 * What it did stays on screen, since some agents may stay on the fork.
 */
export function ReturnForkDialog({
  skillId,
  fork,
  onClose,
}: {
  skillId: string;
  fork: SkillFork;
  onClose: () => void;
}) {
  const t = useTranslations("skills.page.returnFork");
  const tErrors = useTranslations("errors");
  const returnIt = useReturnForkToMain(skillId, fork.id);
  const [returned, setReturned] = useState<ReturnedToMain | null>(null);
  const [error, setError] = useState<string | null>(null);
  return (
    <ConfirmDialog
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
      title={t("title", { name: fork.name })}
      description={returned ? undefined : t("body", { count: fork.agents })}
      confirmLabel={returned ? t("done") : t("confirm")}
      loading={returnIt.isPending}
      onConfirm={async () => {
        if (returned) {
          onClose();
          return;
        }
        setError(null);
        try {
          setReturned(await returnIt.mutateAsync());
        } catch (failure) {
          setError(getErrorMessage(failure, tErrors));
        }
      }}
    >
      {returned && <ReturnedSummary returned={returned} />}
      {error !== null && (
        <p role="alert" className="text-destructive text-sm">
          {error}
        </p>
      )}
    </ConfirmDialog>
  );
}
