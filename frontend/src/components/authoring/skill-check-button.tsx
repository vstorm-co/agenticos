"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui";
import { useSkillAuthoring } from "@/hooks/use-authoring";
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
  const router = useRouter();
  const assistant = useSkillAuthoring(skillId, { enabled: false });
  const [checking, setChecking] = useState(false);
  // A check is an eval run, whose results are runs.
  if (!usePermissions().can(Perm.runsView)) return null;
  return (
    <>
      <Button variant="ghost" size="sm" onClick={() => setChecking(true)}>
        {t("check")}
      </Button>
      {checking && (
        <CheckDialog
          agentId={null}
          proposalId={proposalId}
          estimate={assistant.checkEstimate.mutateAsync}
          start={assistant.check.mutateAsync}
          onStarted={(run) => router.push(`${ROUTES.AGENTS}/${run.agent_id}/evals/${run.id}`)}
          onOpenChange={setChecking}
        />
      )}
    </>
  );
}
