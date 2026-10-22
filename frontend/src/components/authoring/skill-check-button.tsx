"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui";
import { useContextAuthoring, useSkillAuthoring } from "@/hooks/use-authoring";
import { usePermissions } from "@/hooks/use-permissions";
import { ROUTES } from "@/lib/constants";
import { Perm } from "@/types/permissions";
import { CheckDialog } from "./check-dialog";

/**
 * Check a pending skill change with evals before applying it: a dataset runs on
 * an agent that uses the skill, with the proposed body in place of the stored one.
 */
export function SkillCheckButton({ skillId, proposalId }: { skillId: string; proposalId: string }) {
  const t = useTranslations("authoring.skill");
  return (
    <CheckButton
      label={t("check")}
      assistant={useSkillAuthoring(skillId, { enabled: false })}
      proposalId={proposalId}
      subject="skill"
    />
  );
}

/** Check a pending context file change with evals, on an agent that uses the file. */
export function ContextCheckButton({
  contextId,
  proposalId,
  agents,
}: {
  contextId: string;
  proposalId: string;
  /** The agents bound to the file: the only ones the check runs on. */
  agents: { id: string; name: string }[];
}) {
  const t = useTranslations("authoring.context");
  return (
    <CheckButton
      label={t("check")}
      assistant={useContextAuthoring(contextId, { enabled: false })}
      proposalId={proposalId}
      subject="context"
      agents={agents}
    />
  );
}

function CheckButton({
  label,
  assistant,
  proposalId,
  subject,
  agents,
}: {
  label: string;
  assistant: ReturnType<typeof useSkillAuthoring>;
  proposalId: string;
  subject: "skill" | "context";
  agents?: { id: string; name: string }[];
}) {
  const router = useRouter();
  const [checking, setChecking] = useState(false);
  // A check is an eval run, whose results are runs.
  if (!usePermissions().can(Perm.runsView)) return null;
  return (
    <>
      <Button variant="ghost" size="sm" onClick={() => setChecking(true)}>
        {label}
      </Button>
      {checking && (
        <CheckDialog
          agentId={null}
          proposalId={proposalId}
          subject={subject}
          agents={agents}
          estimate={assistant.checkEstimate.mutateAsync}
          start={assistant.check.mutateAsync}
          onStarted={(run) => router.push(`${ROUTES.AGENTS}/${run.agent_id}/evals/${run.id}`)}
          onOpenChange={setChecking}
        />
      )}
    </>
  );
}
