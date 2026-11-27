"use client";

import { useState, type ReactNode } from "react";
import { useTranslations } from "next-intl";
import Link from "next/link";
import { ChevronDown, ListChecks } from "lucide-react";
import {
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from "@/components/ui";
import { useProjectTracking } from "@/hooks/use-project-tracking";
import { useChanged } from "@/hooks/use-changed";
import { usePermissions } from "@/hooks/use-permissions";
import { Perm } from "@/types/permissions";
import type { Project } from "@/types/projects";
import { ROUTES } from "@/lib/constants";
import { ProjectTrackingDialog } from "./project-tracking-dialog";

export function ProjectTrackingControl({
  project,
  primaryAction,
}: {
  project: Project;
  primaryAction: ReactNode;
}) {
  const t = useTranslations("projects.tracking");
  const { can } = usePermissions();
  const { data, isLoading, error, refetch, create } = useProjectTracking(project.id);
  const [open, setOpen] = useState(false);
  const canCreate = can(Perm.agentsEdit) && can(Perm.agentsPublish) && can(Perm.tablesCreate);
  if (useChanged(canCreate) && !canCreate) setOpen(false);
  if (!error && !data && !canCreate) return primaryAction;
  return (
    <>
      <div className="inline-flex items-stretch gap-1">
        {primaryAction}
        <DropdownMenu>
          <span data-tour="project-tracking" className="inline-flex">
            <DropdownMenuTrigger asChild>
              <Button
                variant="outline"
                size="icon"
                className="touch:w-11"
                disabled={isLoading}
                aria-label={t("options")}
                data-tour={!data && canCreate ? "project-tracking-create" : undefined}
              >
                <ChevronDown className="size-4" aria-hidden />
              </Button>
            </DropdownMenuTrigger>
          </span>
          <DropdownMenuContent align="end">
            {error ? (
              <DropdownMenuItem onSelect={() => void refetch()}>{t("loadFailed")}</DropdownMenuItem>
            ) : data ? (
              <DropdownMenuItem asChild>
                <Link href={ROUTES.AGENT_DETAIL(data.agent_id)}>
                  <ListChecks className="size-4" aria-hidden />
                  {t("openTracker")}
                </Link>
              </DropdownMenuItem>
            ) : (
              <DropdownMenuItem onSelect={() => setOpen(true)}>
                <ListChecks className="size-4" aria-hidden />
                {t("title")}
              </DropdownMenuItem>
            )}
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
      {open && canCreate && (
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
