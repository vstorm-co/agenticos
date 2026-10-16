"use client";

import { useState } from "react";
import { FlaskConical, Lock, Plus } from "lucide-react";
import { useTranslations } from "next-intl";

import { PageHeader } from "@/components/dashboard/page-header";
import { CreateDatasetDialog } from "@/components/datasets/create-dataset-dialog";
import { DatasetCard } from "@/components/datasets/dataset-card";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import {
  Button,
  ConfirmDialog,
  ListCard,
  ListCardEmpty,
  PAGE_SIZE,
  Pager,
  SearchInput,
  useDebounced,
} from "@/components/ui";
import { usePermissions } from "@/hooks";
import { useDatasets } from "@/hooks/use-datasets";
import { getErrorMessage } from "@/lib/api-error";
import type { Dataset } from "@/types/datasets";
import { Perm } from "@/types/permissions";

export default function DatasetsPage() {
  const t = useTranslations("datasets");
  const tc = useTranslations("common");
  const tErrors = useTranslations("errors");
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(0);
  const search = useDebounced(query);
  const { datasets, total, isLoading, error, refetch, remove } = useDatasets({
    search,
    sort: "updated",
    skip: page * PAGE_SIZE,
    limit: PAGE_SIZE,
  });
  const { can, isLoading: isLoadingPermissions } = usePermissions();
  const [createOpen, setCreateOpen] = useState(false);
  const [pendingDelete, setPendingDelete] = useState<Dataset | null>(null);
  const canCreate = can(Perm.datasetsEdit);
  const isFiltering = search.trim() !== "";

  const header = (
    <PageHeader
      title={t("title")}
      description={t("pageDescription")}
      actions={
        canCreate ? (
          <Button data-tour="datasets-new" onClick={() => setCreateOpen(true)}>
            <Plus className="h-4 w-4" />
            {t("newDataset")}
          </Button>
        ) : undefined
      }
    />
  );

  if (!isLoadingPermissions && !can(Perm.datasetsView)) {
    return (
      <div className="space-y-6">
        {header}
        <EmptyState icon={Lock} title={t("noAccess")} description={t("noAccessBody")} />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {header}
      <ListCard
        data-tour="datasets-list"
        title={t("title")}
        counted={error || isLoading ? null : t("datasetCount", { count: total })}
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
        ) : datasets.length === 0 ? (
          <ListCardEmpty
            icon={FlaskConical}
            title={isFiltering ? t("noMatches") : t("empty")}
            description={isFiltering ? t("noMatchesBody") : t("emptyBody")}
            cta={
              canCreate && !isFiltering
                ? { label: t("newDataset"), onClick: () => setCreateOpen(true) }
                : undefined
            }
          />
        ) : (
          <div className="space-y-4">
            <div className="rise-in grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
              {datasets.map((dataset) => (
                <DatasetCard
                  key={dataset.id}
                  dataset={dataset}
                  onDelete={() => setPendingDelete(dataset)}
                />
              ))}
            </div>
            <Pager
              page={page}
              pageCount={Math.max(1, Math.ceil(total / PAGE_SIZE))}
              matched={total}
              total={total}
              onPage={setPage}
              counted={t("datasetCount", { count: total })}
            />
          </div>
        )}
      </ListCard>

      <CreateDatasetDialog open={createOpen} onOpenChange={setCreateOpen} />

      {pendingDelete !== null && (
        <ConfirmDialog
          open
          onOpenChange={() => setPendingDelete(null)}
          title={tc("deleteNamedConfirm", { name: pendingDelete.name })}
          description={t("deleteBody")}
          confirmLabel={tc("delete")}
          destructive
          loading={remove.isPending}
          onConfirm={async () => {
            await remove.mutateAsync(pendingDelete.id);
            setPendingDelete(null);
          }}
        />
      )}
    </div>
  );
}
