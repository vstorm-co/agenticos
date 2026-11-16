"use client";

import { useState } from "react";
import { Loader2, Sparkles } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui";
import { useContextAuthoring } from "@/hooks/use-authoring";
import { usePermissions } from "@/hooks/use-permissions";
import { Perm } from "@/types/permissions";
import { ImproveDialog } from "./improve-dialog";

/**
 * Ask the assistant to improve a context file from the runs of the agents that use it.
 *
 * What it proposes waits on the Context page: applying it is live for every
 * agent bound to the file, so it is a decision of its own.
 */
export function ImproveContextButton({
  contextId,
  unsaved = false,
}: {
  contextId: string;
  /** The editor holds changes not saved yet, which the assistant would not read. */
  unsaved?: boolean;
}) {
  const t = useTranslations("authoring.context");
  const canReadRuns = usePermissions().can(Perm.runsView);
  return (
    <ImproveButton
      assistant={useContextAuthoring(contextId, { enabled: canReadRuns })}
      labels={{ improve: t("improve"), working: t("working"), aiOff: t("aiOff") }}
      held={unsaved ? t("saveFirst") : null}
    />
  );
}

function ImproveButton({
  assistant,
  labels,
  held = null,
}: {
  assistant: ReturnType<typeof useContextAuthoring>;
  labels: { improve: string; working: string; aiOff: string };
  /** Why it waits for now, when it does. */
  held?: string | null;
}) {
  const t = useTranslations("authoring");
  const [asking, setAsking] = useState(false);
  const working = assistant.latest?.status === "queued" || assistant.latest?.status === "running";
  // The assistant reads runs, which takes runs:view.
  if (!usePermissions().can(Perm.runsView)) return null;

  return (
    <>
      <Button
        variant="outline"
        disabled={working || held !== null}
        title={held ?? undefined}
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
        <p role="alert" className="text-destructive-ink text-xs">
          {assistant.latest.error}
        </p>
      )}
      {assistant.latest?.status === "completed" && assistant.latest.report?.no_change && (
        <p className="text-muted-foreground text-xs">{t("noChange")}</p>
      )}
      {asking && (
        <ImproveDialog
          kind="improve"
          subject="context"
          estimate={assistant.estimate.mutateAsync}
          start={assistant.start.mutateAsync}
          onOpenChange={setAsking}
        />
      )}
    </>
  );
}
