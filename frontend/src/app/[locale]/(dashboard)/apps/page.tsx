"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Lock, PanelsTopLeft } from "lucide-react";
import { useTranslations } from "next-intl";

import { AgentFilter } from "@/components/artifacts/agent-filter";
import { ArtifactCard } from "@/components/artifacts/artifact-card";
import { PageHeader } from "@/components/dashboard/page-header";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import {
  ListCard,
  ListCardEmpty,
  PAGE_SIZE,
  Pager,
  SearchInput,
  useDebounced,
} from "@/components/ui";
import { GroupFilter, NothingSharedWithGroup } from "@/components/groups/group-filter";
import { usePermissions, useUrlState } from "@/hooks";
import { useArtifactAgents, useArtifacts } from "@/hooks/use-artifacts";
import { getErrorMessage } from "@/lib/api-error";
import { ROUTES } from "@/lib/constants";
import { Perm } from "@/types/permissions";

/**
 * The pages agents published that the caller may open.
 *
 * No create control: an artifact is written by an agent's run, through the
 * Artifacts capability, so the empty state says where one comes from instead.
 */
export default function ArtifactsPage() {
  const t = useTranslations("artifacts");
  const router = useRouter();
  const tc = useTranslations("common");
  const tErrors = useTranslations("errors");
  const [query, setQuery] = useState("");
  const [agentId, setAgentId] = useState<string | null>(null);
  const [page, setPage] = useState(0);
  const search = useDebounced(query);
  // In the address, so a group's apps are a link somebody can send.
  const [groupId, setGroupId] = useUrlState("group");
  const { artifacts, total, isLoading, error, refetch } = useArtifacts({
    search,
    agentId,
    skip: page * PAGE_SIZE,
    limit: PAGE_SIZE,
    groupId,
  });
  const { can, isLoading: isLoadingPermissions } = usePermissions();
  const agents = useArtifactAgents(!isLoadingPermissions && can(Perm.artifactsView));
  const isFiltering = search.trim() !== "" || agentId !== null || groupId !== null;
  const header = <PageHeader title={t("title")} description={t("description")} />;

  if (!isLoadingPermissions && !can(Perm.artifactsView)) {
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
        data-tour="artifacts-list"
        namedByPage
        title={t("title")}
        counted={error || isLoading ? null : t("count", { count: total })}
        empty={!isLoading && !error && !isFiltering && total === 0}
        controls={
          isFiltering || total > 0 ? (
            <div className="flex flex-wrap items-center gap-2">
              <GroupFilter
                value={groupId}
                onChange={(next) => {
                  setGroupId(next);
                  setPage(0);
                }}
              />
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
            </div>
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
        ) : artifacts.length === 0 &&
          groupId !== null &&
          search.trim() === "" &&
          agentId === null ? (
          <NothingSharedWithGroup groupId={groupId} />
        ) : artifacts.length === 0 ? (
          <ListCardEmpty
            icon={PanelsTopLeft}
            title={isFiltering ? t("noMatches") : t("noneYet")}
            description={isFiltering ? t("noMatchesWhy") : t("noneYetWhy")}
            // Somebody with no apps yet is one agent away from one (#2075).
            cta={
              isFiltering
                ? undefined
                : { label: t("noneYetCta"), onClick: () => router.push(ROUTES.AGENTS) }
            }
          />
        ) : (
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
              counted={t("count", { count: total })}
            />
          </div>
        )}
      </ListCard>
    </div>
  );
}
