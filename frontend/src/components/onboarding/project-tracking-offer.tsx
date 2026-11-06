"use client";

import { skipToken, useQuery } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { ConfirmDialog } from "@/components/ui";
import { isAtAgentLimit } from "@/components/agents/agent-limit-notice";
import { useAgentCeiling, useAgents } from "@/hooks/use-agents";
import { usePermissions } from "@/hooks/use-permissions";
import { usePathname } from "@/lib/locale-navigation";
import { qk } from "@/lib/query-keys";
import { useOnboardingStore } from "@/stores/onboarding-store";
import { useAuthStore } from "@/stores/auth-store";
import { Perm } from "@/types/permissions";
import type { Project } from "@/types/projects";
import type { ProjectTracking } from "@/lib/project-tracking-api";

export function ProjectTrackingOffer() {
  const t = useTranslations("onboarding");
  const path = usePathname();
  const projectId = path.split("/")[2] ?? "";
  const { can, scopeOf } = usePermissions();
  const me = useAuthStore((state) => state.user?.id);
  const { agents } = useAgents();
  const { ceiling, known } = useAgentCeiling({ enabled: can(Perm.agentsEdit) });
  const { data: project } = useQuery<Project>({
    queryKey: qk.projects.detail(projectId),
    queryFn: skipToken,
  });
  const { data: tracking } = useQuery<ProjectTracking | null>({
    queryKey: qk.projects.tracking(projectId),
    queryFn: skipToken,
  });
  const openFlow = useOnboardingStore((state) => state.openFlow);
  const dismiss = useOnboardingStore((state) => state.dismissOffer);
  const eligible = agents.some(
    (agent) =>
      agent.can_run &&
      agent.status === "published" &&
      agent.current_version_id !== null &&
      !agent.workflow_id &&
      (scopeOf(Perm.agentsEdit) === "all" || agent.owner_user_id === me),
  );
  if (
    !project?.can_use ||
    tracking !== null ||
    !eligible ||
    !known ||
    isAtAgentLimit(ceiling) ||
    !can(Perm.agentsPublish) ||
    !can(Perm.tablesCreate) ||
    ["queued", "running"].includes(project.workspace_move?.status ?? "")
  )
    return null;
  return (
    <ConfirmDialog
      open
      onOpenChange={(open) => {
        if (!open) dismiss();
      }}
      title={t("offer.create-project-tracker.title")}
      description={t("offer.create-project-tracker.body")}
      confirmLabel={t("offer.accept")}
      cancelLabel={t("offer.decline")}
      onConfirm={() => openFlow("create-project-tracker")}
    />
  );
}
