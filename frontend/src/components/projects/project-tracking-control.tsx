"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { ListChecks } from "lucide-react";
import { Button } from "@/components/ui";
import { useProjectTracking } from "@/hooks/use-project-tracking";
import { usePermissions } from "@/hooks/use-permissions";
import { Perm } from "@/types/permissions";
import type { Project } from "@/types/projects";
import { ROUTES } from "@/lib/constants";
import { ProjectTrackingDialog } from "./project-tracking-dialog";

export function ProjectTrackingControl({ project }: { project: Project }) {
  const t = useTranslations("projects.tracking");
  const { can } = usePermissions();
  const { data, isLoading, error, refetch, create } = useProjectTracking(project.id);
  const [open, setOpen] = useState(false);
  if (isLoading) return null;
  if (error)
    return (
      <Button variant="outline" onClick={() => void refetch()}>
        {t("loadFailed")}
      </Button>
    );
  if (data)
    return (
      <Button variant="outline" asChild>
        <Link href={ROUTES.TABLE_DETAIL(data.table_id)} data-tour="project-tracking">
          <ListChecks className="h-4 w-4" />
          {t("openTasks")}
        </Link>
      </Button>
    );
  if (!can(Perm.agentsEdit) || !can(Perm.agentsPublish) || !can(Perm.tablesCreate)) return null;
  return (
    <>
      <span data-tour="project-tracking">
        <Button variant="outline" onClick={() => setOpen(true)} data-tour="project-tracking-create">
          <ListChecks className="h-4 w-4" />
          {t("title")}
        </Button>
      </span>
      {open && (
        <ProjectTrackingDialog
          project={project}
          pending={create.isPending}
          onClose={() => setOpen(false)}
          onCreate={(input, onSuccess) => create.mutate(input, { onSuccess })}
        />
      )}
    </>
  );
}
