"use client";

import { useState } from "react";
import { LayoutTemplate } from "lucide-react";
import { useTranslations } from "next-intl";

import { ArtifactCard } from "@/components/artifacts/artifact-card";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { PAGE_SIZE, Pager } from "@/components/ui";
import { useArtifacts } from "@/hooks/use-artifacts";
import { getErrorMessage } from "@/lib/api-error";
import type { Project } from "@/types/projects";

/**
 * The apps the project's chats published, as the Apps gallery shows them.
 *
 * Only those the reader may open: an app keeps its own audience, so one a
 * teammate built and has not shared is not listed here either.
 */
export function ProjectApps({ project }: { project: Project }) {
  const t = useTranslations("projects");
  const tErrors = useTranslations("errors");
  // Paged as the Apps gallery is: a busy project outgrows any one page, and
  // the apps past it would otherwise be found nowhere from the project.
  const [page, setPage] = useState(0);
  const { artifacts, total, isLoading, error } = useArtifacts({
    projectId: project.id,
    skip: page * PAGE_SIZE,
    limit: PAGE_SIZE,
  });

  if (isLoading)
    return (
      <LoadingState
        variant="skeleton-cards"
        className="grid-cols-1 sm:grid-cols-1 md:grid-cols-2"
      />
    );
  if (error) return <ErrorState description={getErrorMessage(error, tErrors)} />;
  if (artifacts.length === 0) {
    return (
      <EmptyState icon={LayoutTemplate} title={t("noAppsYet")} description={t("noAppsHint")} />
    );
  }
  return (
    <div className="space-y-4">
      <div className="rise-in grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
        {artifacts.map((artifact) => (
          <ArtifactCard key={artifact.id} artifact={artifact} />
        ))}
      </div>
      <Pager
        page={page}
        pageCount={Math.max(1, Math.ceil(total / PAGE_SIZE))}
        matched={total}
        total={total}
        onPage={setPage}
        counted={t("appCount", { count: total })}
      />
    </div>
  );
}
