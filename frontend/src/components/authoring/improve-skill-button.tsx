"use client";

import { useState } from "react";
import { Loader2, Sparkles } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui";
import { useSkillAuthoring } from "@/hooks/use-authoring";
import { useAiAssistance } from "@/hooks/use-organizations";
import { ImproveDialog } from "./improve-dialog";

/**
 * Ask the assistant to improve a skill from the runs that opened it.
 *
 * What it proposes waits under Skills like any other change: applying a skill
 * change is live for every agent bound to it, so it is a decision of its own.
 */
export function ImproveSkillButton({ skillId }: { skillId: string }) {
  const t = useTranslations("authoring.skill");
  const { enabled } = useAiAssistance();
  const assistant = useSkillAuthoring(skillId);
  const [asking, setAsking] = useState(false);
  const working = assistant.latest?.status === "queued" || assistant.latest?.status === "running";

  return (
    <>
      <Button
        variant="outline"
        disabled={enabled === false || working}
        title={enabled === false ? t("aiOff") : undefined}
        onClick={() => setAsking(true)}
      >
        {working ? (
          <Loader2 className="h-4 w-4 animate-spin" aria-hidden />
        ) : (
          <Sparkles className="h-4 w-4" aria-hidden />
        )}
        {working ? t("working") : t("improve")}
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
