"use client";

import { use } from "react";
import Link from "next/link";
import { FolderKanban, Plus } from "lucide-react";
import { useTranslations } from "next-intl";

import { PageHeader } from "@/components/dashboard/page-header";
import { ProjectApps } from "@/components/projects/project-apps";
import { ProjectChats } from "@/components/projects/project-chats";
import { FileExplorer } from "@/components/sandboxes/workspace-explorer";
import { Skeleton } from "@/components/ui/skeleton";
import { ProjectFiles } from "@/components/projects/project-files";
import { ProjectSettings } from "@/components/projects/project-settings";
import { ShareResourceButton } from "@/components/sharing/share-resource-button";
import { AudienceChip } from "@/components/sharing/audience-chip";
import { ErrorState, LoadingState } from "@/components/states";
import { Button, Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui";
import { useUrlState } from "@/hooks";
import { useProject } from "@/hooks/use-projects";
import { getErrorMessage } from "@/lib/api-error";
import { ROUTES } from "@/lib/constants";

// Files first: a project is the work kept in it, and its chats are how the work
// was done.
const TABS = ["files", "chats", "apps", "instructions"] as const;
type Tab = (typeof TABS)[number];

/**
 * One project: its chats, the files every agent in it shares, and the
 * instructions they all read. The tab is in the address, so "look at the files
 * in Launch" is a link.
 */
export default function ProjectPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const t = useTranslations("projects");
  const tErrors = useTranslations("errors");
  const { project, isLoading, error } = useProject(id);
  const [tabParam, setTabParam] = useUrlState("tab");
  const tab: Tab = TABS.find((entry) => entry === tabParam) ?? "files";

  if (error || (project === null && !isLoading)) {
    return <ErrorState description={getErrorMessage(error, tErrors)} />;
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-6 overflow-hidden pb-4">
      <PageHeader
        className="mb-0 shrink-0 md:mb-0"
        breadcrumbs={[
          { label: t("title"), href: ROUTES.PROJECTS },
          { label: project?.name ?? t("title") },
        ]}
        title={
          <span className="flex items-center gap-3">
            <span className="bg-muted flex h-9 w-9 shrink-0 items-center justify-center rounded-xl">
              <FolderKanban className="h-5 w-5" aria-hidden />
            </span>
            {project?.name ?? (
              <span
                aria-hidden
                className="bg-muted inline-block h-7 w-48 animate-pulse rounded-md"
              />
            )}
          </span>
        }
        description={project?.description ?? undefined}
        badges={
          project ? (
            <AudienceChip visibility={project.visibility} groups={project.shared_groups} />
          ) : (
            <Skeleton className="h-5 w-20" />
          )
        }
        actions={
          project ? (
            <>
              <ShareResourceButton
                resourceType="project"
                resourceId={project.id}
                name={project.name}
                canManage={project.can_edit}
              />
              {project.can_use &&
                !["queued", "running"].includes(project.workspace_move?.status ?? "") && (
                  <Button asChild>
                    <Link href={ROUTES.PROJECT_CHAT(project.id)}>
                      <Plus className="h-4 w-4" />
                      {t("newChat")}
                    </Link>
                  </Button>
                )}
            </>
          ) : (
            <Skeleton className="h-9 w-28" />
          )
        }
      />

      <Tabs
        value={tab}
        onValueChange={(value) => setTabParam(value === "files" ? null : value)}
        className="flex min-h-0 flex-1 flex-col"
      >
        <TabsList data-tour="project-tabs" className="shrink-0">
          <TabsTrigger disabled={isLoading} value="files">
            {t("files")}
          </TabsTrigger>
          <TabsTrigger disabled={isLoading} value="chats">
            {t("chats")}
          </TabsTrigger>
          <TabsTrigger disabled={isLoading} value="apps">
            {t("apps")}
          </TabsTrigger>
          <TabsTrigger disabled={isLoading} value="instructions">
            {t("instructions")}
          </TabsTrigger>
        </TabsList>
        <TabsContent value="files" className="flex min-h-0 flex-1 flex-col overflow-hidden">
          {project ? (
            <ProjectFiles project={project} />
          ) : (
            <FileExplorer source={{ kind: "project", id }} files={null} isLoading error={null} />
          )}
        </TabsContent>
        <TabsContent value="chats" className="flex min-h-0 flex-1 flex-col overflow-auto">
          {project ? (
            <ProjectChats project={project} />
          ) : (
            <LoadingState variant="skeleton-list" rows={3} />
          )}
        </TabsContent>
        <TabsContent value="apps" className="flex min-h-0 flex-1 flex-col overflow-auto">
          {project ? (
            <ProjectApps project={project} />
          ) : (
            <LoadingState
              variant="skeleton-cards"
              className="grid-cols-1 sm:grid-cols-1 md:grid-cols-2"
            />
          )}
        </TabsContent>
        <TabsContent value="instructions" className="min-h-0 flex-1 overflow-auto">
          {/* Keyed on the saved row, so a save that comes back re-seeds the form. */}
          {project ? (
            <ProjectSettings key={project.updated_at ?? project.id} project={project} />
          ) : (
            <div className="space-y-6">
              <Skeleton className="h-80 w-full rounded-2xl" />
              <Skeleton className="h-64 w-full rounded-2xl" />
            </div>
          )}
        </TabsContent>
      </Tabs>
    </div>
  );
}
