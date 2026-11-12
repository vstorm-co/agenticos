"use client";

import { useState } from "react";
import { CheckCircle2, Loader2 } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui";
import { useOpenSkillCheck } from "@/hooks/use-skill-check";
import { getErrorMessage } from "@/lib/api-error";
import { SkillCheckDialog, type CheckedDraft } from "./skill-check-dialog";

/**
 * A check of a change to the line shown that a person left running, or that finished
 * and waits for a decision: where they come back to it, with Show to open it again,
 * and from there back to editing the text it checked. When the line's checks cannot
 * be read it says so, with Retry, rather than looking like a line with none open.
 */
export function CheckRunning({
  skillId,
  forkId,
  onEdit,
}: {
  skillId: string;
  forkId: string | null;
  onEdit: (draft: CheckedDraft) => void;
}) {
  const t = useTranslations("skills.page.checkRunning");
  const tCommon = useTranslations("common");
  const tErrors = useTranslations("errors");
  const { check, error, refetch } = useOpenSkillCheck(skillId, forkId);
  const [open, setOpen] = useState(false);
  if (check === null && error) {
    return (
      <div
        role="alert"
        className="bg-card flex flex-wrap items-center justify-between gap-3 rounded-xl border px-4 py-3"
      >
        <p className="text-sm">{t("unreadable", { reason: getErrorMessage(error, tErrors) })}</p>
        <Button variant="outline" size="sm" onClick={() => void refetch()}>
          {tCommon("retry")}
        </Button>
      </div>
    );
  }
  if (check === null) return null;
  const running = check.status === "running";
  const done = check.agents.filter(
    (row) => row.state !== "queued" && row.state !== "running",
  ).length;
  return (
    <div
      role="status"
      className="bg-card flex flex-wrap items-center justify-between gap-3 rounded-xl border px-4 py-3"
    >
      <p className="flex items-center gap-2 text-sm">
        {running ? (
          <Loader2
            className="text-primary size-4 animate-spin motion-reduce:animate-none"
            aria-hidden
          />
        ) : (
          <CheckCircle2 className="text-success size-4" aria-hidden />
        )}
        {running
          ? t("running", { done, total: check.agents.length })
          : t("finished", { total: check.agents.length })}
      </p>
      <Button variant="outline" size="sm" onClick={() => setOpen(true)}>
        {t("show")}
      </Button>
      {open && (
        <SkillCheckDialog
          skillId={skillId}
          resume={check.id}
          forkId={forkId}
          onOpenChange={setOpen}
          onEdit={onEdit}
        />
      )}
    </div>
  );
}
