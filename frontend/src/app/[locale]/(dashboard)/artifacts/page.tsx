"use client";

import { useState } from "react";
import { Lock, PanelsTopLeft } from "lucide-react";
import { useTranslations } from "next-intl";

import { AgentFilter } from "@/components/artifacts/agent-filter";
import {
  ArchiveArtifactDialog,
  DeleteArtifactDialog,
} from "@/components/artifacts/artifact-archive";
import { ArtifactCard } from "@/components/artifacts/artifact-card";
import { PageHeader } from "@/components/dashboard/page-header";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import {
  ListCard,
  ListCardEmpty,
  PAGE_SIZE,
  Pager,
  SearchInput,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  useDebounced,
} from "@/components/ui";
import { usePermissions } from "@/hooks";
import { useArtifactAgents, useArtifactListActions, useArtifacts } from "@/hooks/use-artifacts";
import { useUrlState } from "@/hooks/use-url-state";
import { getErrorMessage } from "@/lib/api-error";
import type { Artifact } from "@/types/artifact";
import { Perm } from "@/types/permissions";

type Shown = "live" | "all";
const SHOWN: readonly Shown[] = ["live", "all"];

/**
 * The pages agents published that the caller may open.
 *
 * No create control: an artifact is written by an agent's run, through the
 * Artifacts capability, so the empty state says where one comes from instead.
 */
export default function ArtifactsPage() {
  const t = useTranslations("artifacts");
  const tc = useTranslations("common");
  const tErrors = useTranslations("errors");
  const [query, setQuery] = useState("");
  const [agentId, setAgentId] = useState<string | null>(null);
  const [page, setPage] = useState(0);
  const search = useDebounced(query);
  // Kept in the URL like the tables list's, so a link can open the archive.
  const [shownParam, setShownParam] = useUrlState("show");
  const shown: Shown = shownParam === "all" ? "all" : "live";
  const { artifacts, total, isLoading, error, refetch } = useArtifacts({
    search,
    agentId,
    includeArchived: shown === "all",
    skip: page * PAGE_SIZE,
    limit: PAGE_SIZE,
  });
  const { can, isLoading: isLoadingPermissions } = usePermissions();
  const agents = useArtifactAgents(!isLoadingPermissions && can(Perm.artifactsView));
  // The role's edit right, as the agents and workflows lists gate their menus:
  // the server still decides each page, and refuses one the caller may not change.
  const canEdit = can(Perm.artifactsEdit);
  const { archive, unarchive, remove } = useArtifactListActions();
  const [pendingArchive, setPendingArchive] = useState<Artifact | null>(null);
  const [pendingDelete, setPendingDelete] = useState<Artifact | null>(null);
  const busyId = archive.isPending
    ? archive.variables
    : unarchive.isPending
      ? unarchive.variables
      : remove.isPending
        ? remove.variables
        : undefined;
  const isFiltering = search.trim() !== "" || agentId !== null || shown === "all";
  const header = <PageHeader title={t("title")} description={t("description")} />;

  if (!isLoadingPermissions && !can(Perm.artifactsView)) {
    return (
      <div className="space-y-6">
        {header}
        <EmptyState icon={Lock} title={t("cannotSee")} description={t("askForAccess")} />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {header}
      <ListCard
        data-tour="artifacts-list"
        title={t("title")}
        counted={error || isLoading ? null : t("count", { count: total })}
        // Which pages to show is always offered: when every page is archived the
        // live list is empty, and this is the one way to reach them.
        controls={
          <div className="flex flex-wrap items-center gap-2">
            {(isFiltering || total > 0) && (
              <>
                <AgentFilter
                  agents={agents}
                  value={agentId}
                  onChange={(next) => {
                    setAgentId(next);
                    setPage(0);
                  }}
                />
                <SearchInput
                  value={query}
                  onChange={(next) => {
                    setQuery(next);
                    setPage(0);
                  }}
                  placeholder={t("search")}
                  className="sm:w-56"
                />
              </>
            )}
            <Select
              value={shown}
              onValueChange={(value) => {
                setShownParam(value === "all" ? "all" : null);
                setPage(0);
              }}
            >
              <SelectTrigger className="w-full sm:w-44" aria-label={t("shownFilter")}>
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                {SHOWN.map((value) => (
                  <SelectItem key={value} value={value}>
                    {t(`shown.${value}`)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        }
      >
        {isLoading || isLoadingPermissions ? (
          <LoadingState variant="skeleton-cards" rows={3} />
        ) : error ? (
          <ErrorState
            description={getErrorMessage(error, tErrors)}
            cta={{ label: tc("retry"), onClick: () => void refetch() }}
          />
        ) : artifacts.length === 0 ? (
          <ListCardEmpty
            icon={PanelsTopLeft}
            title={isFiltering ? t("noMatches") : t("noneYet")}
            description={isFiltering ? t("noMatchesWhy") : t("noneYetWhy")}
          />
        ) : (
          <div className="space-y-4">
            <div className="rise-in grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
              {artifacts.map((artifact) => (
                <ArtifactCard
                  key={artifact.id}
                  artifact={artifact}
                  busy={busyId === artifact.id}
                  actions={
                    canEdit
                      ? {
                          onArchive: () => setPendingArchive(artifact),
                          onRestore: () => unarchive.mutate(artifact.id),
                          onDelete: () => setPendingDelete(artifact),
                        }
                      : undefined
                  }
                />
              ))}
            </div>
            <Pager
              page={page}
              pageCount={Math.max(1, Math.ceil(total / PAGE_SIZE))}
              matched={total}
              total={total}
              onPage={setPage}
              counted={t("count", { count: total })}
            />
          </div>
        )}
      </ListCard>

      {pendingArchive && (
        <ArchiveArtifactDialog
          open
          onOpenChange={() => setPendingArchive(null)}
          title={pendingArchive.title}
          loading={archive.isPending}
          onConfirm={() =>
            archive.mutate(pendingArchive.id, { onSuccess: () => setPendingArchive(null) })
          }
        />
      )}
      {pendingDelete && (
        <DeleteArtifactDialog
          open
          onOpenChange={() => setPendingDelete(null)}
          title={pendingDelete.title}
          loading={remove.isPending}
          onConfirm={() =>
            remove.mutate(pendingDelete.id, { onSuccess: () => setPendingDelete(null) })
          }
        />
      )}
    </div>
  );
}
