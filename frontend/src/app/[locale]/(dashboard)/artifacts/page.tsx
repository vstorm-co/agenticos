"use client";

import { useState } from "react";
import { Lock, PanelsTopLeft } from "lucide-react";
import { useTranslations } from "next-intl";

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
import { usePermissions } from "@/hooks";
import { useArtifacts } from "@/hooks/use-artifacts";
import { getErrorMessage } from "@/lib/api-error";
import { Perm } from "@/types/permissions";

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
  const [page, setPage] = useState(0);
  const search = useDebounced(query);
  const { artifacts, total, isLoading, error, refetch } = useArtifacts({
    search,
    skip: page * PAGE_SIZE,
    limit: PAGE_SIZE,
  });
  const { can, isLoading: isLoadingPermissions } = usePermissions();
  const isFiltering = search.trim() !== "";
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
        controls={
          isFiltering || total > 0 ? (
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
        ) : artifacts.length === 0 ? (
          <ListCardEmpty
            icon={PanelsTopLeft}
            title={isFiltering ? t("noMatches") : t("noneYet")}
            description={isFiltering ? t("noMatchesWhy") : t("noneYetWhy")}
          />
        ) : (
          <div className="space-y-4">
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
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
