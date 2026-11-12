"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";
import { useTranslations } from "next-intl";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui";
import { ErrorState, LoadingState } from "@/components/states";
import { EditSkillDialog } from "./edit-skill-dialog";
import { DeleteSkillDialog } from "./delete-skill-dialog";
import { eachAgentOnce } from "./skill-lines";
import { useSkill } from "@/hooks";
import { useSkillAgents, useSkillVersions } from "@/hooks/use-skill-versions";
import { usePermissions } from "@/hooks/use-permissions";
import { getErrorMessage } from "@/lib/api-error";
import { ROUTES } from "@/lib/constants";
import { Perm } from "@/types/permissions";

/** The catalog opens the skill's instructions and files; history is a deliberate next step. */
export function SkillDetailDialog({ id, onClose }: { id: string; onClose: () => void }) {
  const t = useTranslations("skills.page");
  const errors = useTranslations("errors");
  const router = useRouter();
  const { can } = usePermissions();
  const { skill, error, remove } = useSkill(id);
  const versions = useSkillVersions(id, null, 0);
  const agents = useSkillAgents(id);
  const [deleting, setDeleting] = useState(false);
  const failed = error ?? versions.error ?? agents.error;
  if (failed || !skill || versions.isLoading || agents.isLoading) {
    return (
      <Dialog
        open
        onOpenChange={(open) => {
          if (!open) onClose();
        }}
      >
        <DialogContent>
          <DialogTitle>{t("skillDetails")}</DialogTitle>
          {failed ? (
            <ErrorState description={getErrorMessage(failed, errors)} />
          ) : (
            <LoadingState variant="skeleton-panel" rows={3} />
          )}
        </DialogContent>
      </Dialog>
    );
  }
  return (
    <>
      <EditSkillDialog
        skill={skill}
        fork={null}
        followers={versions.versions[0]?.agents ?? 0}
        readers={eachAgentOnce(
          (agents.agents?.items ?? []).filter(
            (usage) => !usage.draft_only && usage.binding.state === "main",
          ),
        ).map((usage) => usage.agent.name)}
        canCheck={can(Perm.runsView)}
        onClose={onClose}
        onDelete={() => setDeleting(true)}
        onOpenFull={() => router.push(`${ROUTES.SKILL_DETAIL(id)}?tab=content`)}
      />
      {deleting && (
        <DeleteSkillDialog
          skill={skill}
          agents={agents.agents}
          agentsError={agents.error}
          deleting={remove.isPending}
          onClose={() => setDeleting(false)}
          onDelete={async (removeFromAgents) => {
            await remove.mutateAsync(removeFromAgents);
            onClose();
          }}
        />
      )}
    </>
  );
}
