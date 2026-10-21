"use client";

import { useState } from "react";
import { Loader2, Sparkles } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui";
import { useContextAuthoring, useSkillAuthoring } from "@/hooks/use-authoring";
import { useAiAssistance } from "@/hooks/use-organizations";
import { usePermissions } from "@/hooks/use-permissions";
import { Perm } from "@/types/permissions";
import { ImproveDialog } from "./improve-dialog";

/**
 * Ask the assistant to improve a skill from the runs that opened it.
 *
 * What it proposes waits under Skills like any other change: applying a skill
 * change is live for every agent bound to it, so it is a decision of its own.
 */
export function ImproveSkillButton({ skillId }: { skillId: string }) {
  const t = useTranslations("authoring.skill");
  return (
    <ImproveButton
      assistant={useSkillAuthoring(skillId)}
      labels={{ improve: t("improve"), working: t("working"), aiOff: t("aiOff") }}
    />
  );
}

/**
 * Ask the assistant to improve a context file from the runs of the agents that use it.
 *
 * What it proposes waits on the Context page: applying it is live for every
 * agent bound to the file, so it is a decision of its own.
 */
export function ImproveContextButton({ contextId }: { contextId: string }) {
  const t = useTranslations("authoring.context");
  return (
    <ImproveButton
      assistant={useContextAuthoring(contextId)}
      labels={{ improve: t("improve"), working: t("working"), aiOff: t("aiOff") }}
    />
  );
}

function ImproveButton({
  assistant,
  labels,
}: {
  assistant: ReturnType<typeof useSkillAuthoring>;
  labels: { improve: string; working: string; aiOff: string };
}) {
  const { enabled } = useAiAssistance();
  const [asking, setAsking] = useState(false);
  const working = assistant.latest?.status === "queued" || assistant.latest?.status === "running";
  // The assistant reads runs, which takes runs:view.
  if (!usePermissions().can(Perm.runsView)) return null;

  return (
    <>
      <Button
        variant="outline"
        disabled={enabled === false || working}
        title={enabled === false ? labels.aiOff : undefined}
        onClick={() => setAsking(true)}
      >
        {working ? (
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
        ) : (
          <Sparkles className="h-4 w-4" aria-hidden />
        )}
        {working ? labels.working : labels.improve}
      </Button>
      {assistant.latest?.status === "failed" && (
        <p role="alert" className="text-destructive text-xs">
          {assistant.latest.error}
        </p>
      )}
      {asking && (
        <ImproveDialog
          kind="improve"
          estimate={assistant.estimate.mutateAsync}
          start={assistant.start.mutateAsync}
          onOpenChange={setAsking}
        />
      )}
    </>
  );
}
