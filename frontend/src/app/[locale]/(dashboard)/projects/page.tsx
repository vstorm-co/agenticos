"use client";

import { useState } from "react";
import { FolderKanban, Lock, Plus } from "lucide-react";
import { useTranslations } from "next-intl";

import { PageHeader } from "@/components/dashboard/page-header";
import { CreateProjectDialog } from "@/components/projects/create-project-dialog";
import { ProjectCard } from "@/components/projects/project-card";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import {
  Button,
  ListCard,
  ListCardEmpty,
  PAGE_SIZE,
  Pager,
  SearchInput,
  useDebounced,
} from "@/components/ui";
import { usePermissions } from "@/hooks";
import { useProjects } from "@/hooks/use-projects";
import { getErrorMessage } from "@/lib/api-error";
import { ROUTES } from "@/lib/constants";
import { useRouter } from "@/lib/locale-navigation";
import { Perm } from "@/types/permissions";

/**
 * Projects: instructions and files shared by every chat started in them.
 *
 * A grid of cards, the same shape as skills and context, because a project is a
 * thing somebody returns to rather than a row in a table.
 */
export default function ProjectsPage() {
  const t = useTranslations("projects");
  const tc = useTranslations("common");
  const tErrors = useTranslations("errors");
  const router = useRouter();
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(0);
  const search = useDebounced(query);
  const [createOpen, setCreateOpen] = useState(false);
  const { projects, total, isLoading, error, refetch } = useProjects({
    search,
    skip: page * PAGE_SIZE,
    limit: PAGE_SIZE,
  });
  const { can, isLoading: isLoadingPermissions } = usePermissions();
  const canCreate = can(Perm.projectsEdit);
  const isSearching = search.trim() !== "";

  const header = (
    <PageHeader
      title={t("title")}
      description={t("pageDescription")}
      actions={
        canCreate ? (
          <Button data-tour="projects-new" onClick={() => setCreateOpen(true)}>
            <Plus className="h-4 w-4" />
            {t("newProject")}
          </Button>
        ) : undefined
      }
    />
  );

  if (!isLoadingPermissions && !can(Perm.projectsView)) {
    return (
      <div className="flex flex-1 flex-col space-y-6">
        {header}
        <EmptyState icon={Lock} title={t("cannotSee")} description={t("askForAccess")} />
      </div>
    );
  }

  return (
    <div className="flex flex-1 flex-col space-y-6">
      {header}
      <ListCard
        fill
        data-tour="projects-list"
        namedByPage
        title={t("title")}
        counted={error || isLoading ? null : t("projectCount", { count: total })}
        empty={!isLoading && !error && !isSearching && total === 0}
        controls={
          isSearching || total > 0 ? (
            <SearchInput
              value={query}
              onChange={(next) => {
                setQuery(next);
                setPage(0);
              }}
              placeholder={t("search")}
              className="sm:w-56"
            />
          ) : undefined
        }
      >
        {isLoading || isLoadingPermissions ? (
          <LoadingState variant="skeleton-cards" rows={3} />
        ) : error ? (
          <ErrorState
            description={getErrorMessage(error, tErrors)}
            cta={{ label: tc("retry"), onClick: () => void refetch() }}
          />
        ) : projects.length === 0 ? (
          <ListCardEmpty
            icon={FolderKanban}
            title={isSearching ? t("noMatches") : t("noProjectsYet")}
            description={isSearching ? t("searchedNames") : t("noProjectsHint")}
            cta={
              canCreate && !isSearching
                ? {
                    label: (
                      <>
                        <Plus className="h-3.5 w-3.5" />
                        {t("newProject")}
                      </>
                    ),
                    onClick: () => setCreateOpen(true),
                  }
                : undefined
            }
          />
        ) : (
          <>
            <div className="rise-in grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
              {projects.map((project) => (
                <ProjectCard key={project.id} project={project} />
              ))}
            </div>
            <Pager
              page={page}
              pageCount={Math.max(1, Math.ceil(total / PAGE_SIZE))}
              matched={total}
              total={total}
              onPage={setPage}
              counted={t("projectCount", { count: total })}
            />
          </>
        )}
      </ListCard>

      <CreateProjectDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        onCreated={(project) => {
          setCreateOpen(false);
          router.push(ROUTES.PROJECT_DETAIL(project.id));
        }}
      />
    </div>
  );
}
