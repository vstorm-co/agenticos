"use client";

import { useRouter } from "next/navigation";
import { lazy, Suspense, useState } from "react";
import { useTranslations } from "next-intl";
import { ErrorState } from "@/components/states";
import { SkillEditorFrame } from "./skill-editor-frame";
import { EditorLoading } from "@/components/files/editor-loading";
import { DeleteSkillDialog } from "./delete-skill-dialog";
import { eachAgentOnce } from "./skill-lines";
import { useSkill } from "@/hooks";
import { useSkillAgents, useSkillVersions } from "@/hooks/use-skill-versions";
import { usePermissions } from "@/hooks/use-permissions";
import { getErrorMessage } from "@/lib/api-error";
import { ROUTES } from "@/lib/constants";
import { Perm } from "@/types/permissions";

const EditSkillDialogBody = lazy(() =>
  import("./edit-skill-dialog").then((module) => ({ default: module.EditSkillDialogBody })),
);

/** The catalog opens the skill's instructions and files; history is a deliberate next step. */
export function SkillDetailDialog({
  id,
  name,
  canEdit,
  onClose,
}: {
  id: string;
  name?: string;
  canEdit?: boolean;
  onClose: () => void;
}) {
  const t = useTranslations("skills.page");
  const errors = useTranslations("errors");
  const router = useRouter();
  const { can } = usePermissions();
  const { skill, error, remove } = useSkill(id);
  const versions = useSkillVersions(id, null, 0);
  const agents = useSkillAgents(id);
  const [deleting, setDeleting] = useState(false);
  const [busy, setBusy] = useState(false);
  const failed = error ?? versions.error ?? agents.error;
  const loading = !skill || versions.isLoading || agents.isLoading;
  const placeholder = <EditorLoading kind="skill" canEdit={skill?.can_edit ?? canEdit} fullView />;
  return (
    <>
      <SkillEditorFrame
        id={id}
        title={skill?.name ?? name ?? t("skillDetails")}
        busy={busy}
        onClose={onClose}
      >
        {failed ? (
          <ErrorState description={getErrorMessage(failed, errors)} />
        ) : loading || !skill ? (
          placeholder
        ) : (
          <Suspense fallback={placeholder}>
            <EditSkillDialogBody
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
              onBusyChange={setBusy}
            />
          </Suspense>
        )}
      </SkillEditorFrame>
      {deleting && skill && (
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
