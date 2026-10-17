"use client";

import { LayoutTemplate } from "lucide-react";
import { useTranslations } from "next-intl";

import { ArtifactCard } from "@/components/artifacts/artifact-card";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
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
  const { artifacts, isLoading, error } = useArtifacts({ projectId: project.id, limit: 60 });

  if (isLoading) return <LoadingState variant="skeleton-cards" />;
  if (error) return <ErrorState description={getErrorMessage(error, tErrors)} />;
  if (artifacts.length === 0) {
    return (
      <EmptyState icon={LayoutTemplate} title={t("noAppsYet")} description={t("noAppsHint")} />
    );
  }
  return (
    <div className="rise-in grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
      {artifacts.map((artifact) => (
        <ArtifactCard key={artifact.id} artifact={artifact} />
      ))}
    </div>
  );
}
