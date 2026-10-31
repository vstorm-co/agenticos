"use client";

import { useWorkspaceFullscreen } from "@/hooks/use-workspace-fullscreen";
import { WorkspaceFullscreenButton } from "@/components/ui/workspace-fullscreen-button";
import { useState } from "react";
import { ListFilters } from "@/components/ui/list-filters";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";
import { Plus, Table2 } from "lucide-react";

import { ErrorState } from "@/components/states";
import { PageHeader } from "@/components/dashboard/page-header";
import { type CsvStart, CreateTableDialog } from "@/components/tables/create-table-dialog";
import { type CsvPreset, ImportCsvDialog } from "@/components/tables/import-csv-dialog";
import { TableCard } from "@/components/tables/table-card";
import {
  Button,
  ListCard,
  ListCardEmpty,
  PAGE_SIZE,
  PaginationBar,
  SearchInput,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Skeleton,
  useDebounced,
} from "@/components/ui";
import { useTables, usePermissions } from "@/hooks";
import { useUrlState } from "@/hooks/use-url-state";
import { ROUTES } from "@/lib/constants";
import { Perm } from "@/types/permissions";
import type { TableRead } from "@/types/tables";

type Shown = "live" | "all";
const SHOWN: readonly Shown[] = ["live", "all"];

/** The file a table was started from, mapped onto the columns it was created with. */
function presetFor(table: TableRead, csv: CsvStart): CsvPreset {
  return {
    fileName: csv.fileName,
    headers: csv.headers,
    rows: csv.rows,
    mapping: csv.labels.map(
      (label) => table.columns.find((column) => column.label === label)?.id ?? null,
    ),
  };
}

export default function TablesPage() {
  const {
    ref: galleryRef,
    expanded: galleryFullscreen,
    toggle: toggleGalleryFullscreen,
  } = useWorkspaceFullscreen();
  const t = useTranslations("pages.tables");
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(0);
  const search = useDebounced(query);
  // Kept in the URL like the workflows list's status, so a link can open the archive.
  const [shownParam, setShownParam] = useUrlState("show");
  const shown: Shown = shownParam === "all" ? "all" : "live";
  const { tables, total, isLoading, error, refetch, create } = useTables({
    search,
    includeArchived: shown === "all",
    skip: page * PAGE_SIZE,
    limit: PAGE_SIZE,
  });
  const { can } = usePermissions();
  const canCreate = can(Perm.tablesCreate);
  const [createOpen, setCreateOpen] = useState(false);
  const [importing, setImporting] = useState<{ table: TableRead; preset: CsvPreset } | null>(null);
  const router = useRouter();
  const tc = useTranslations("common");

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-6">
      <PageHeader
        title={t("title")}
        description={t("description")}
        actions={
          canCreate ? (
            <Button data-tour="tables-new" onClick={() => setCreateOpen(true)}>
              <Plus className="h-4 w-4" /> {t("newTable")}
            </Button>
          ) : undefined
        }
      />

      <ListCard
        ref={galleryRef}
        fill
        role={galleryFullscreen ? "dialog" : undefined}
        aria-modal={galleryFullscreen || undefined}
        aria-label={t("catalog")}
        className={
          galleryFullscreen ? "fixed inset-0 z-40 overflow-y-auto rounded-none" : undefined
        }
        namedByPage
        title={t("catalog")}
        counted={isLoading ? null : t("shownCount", { count: total })}
        controls={
          <div className="flex min-w-0 flex-wrap items-center gap-2">
            <WorkspaceFullscreenButton
              expanded={galleryFullscreen}
              onToggle={toggleGalleryFullscreen}
            />
            <SearchInput
              className="min-w-0 flex-1 sm:flex-none"
              value={query}
              onChange={(next) => {
                setQuery(next);
                setPage(0);
              }}
              placeholder={t("searchPlaceholder")}
            />
            <ListFilters compact active={Number(shown !== "live")}>
              <Select
                value={shown}
                onValueChange={(value) => {
                  setShownParam(value === "all" ? "all" : null);
                  setPage(0);
                }}
              >
                <SelectTrigger className="w-44" aria-label={t("shownFilter")}>
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
            </ListFilters>
          </div>
        }
        data-tour="tables-catalog"
      >
        {isLoading && tables.length === 0 ? (
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
            {[0, 1, 2].map((row) => (
              <Skeleton key={row} className="h-36 w-full rounded-xl" />
            ))}
          </div>
        ) : error && tables.length === 0 ? (
          <ErrorState cta={{ label: tc("retry"), onClick: () => void refetch() }} />
        ) : tables.length === 0 ? (
          <ListCardEmpty
            icon={Table2}
            title={search ? t("empty.filteredTitle") : t("empty.title")}
            description={search ? undefined : t("empty.description")}
            cta={
              canCreate && !search
                ? { label: t("newTable"), onClick: () => setCreateOpen(true) }
                : undefined
            }
          />
        ) : (
          <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
            {tables.map((table) => (
              <TableCard key={table.id} table={table} />
            ))}
          </div>
        )}
        {total > PAGE_SIZE && (
          <div>
            <PaginationBar
              page={page}
              pageSize={PAGE_SIZE}
              total={total}
              isLoading={isLoading}
              onPage={setPage}
            />
          </div>
        )}
      </ListCard>

      <CreateTableDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        onCreate={(input, csv) =>
          create.mutate(input, {
            onSuccess: (table) => {
              setCreateOpen(false);
              // Started from a file: its rows go in first, with the progress
              // and every row that did not make it in view, then the table.
              if (csv) setImporting({ table, preset: presetFor(table, csv) });
              else router.push(ROUTES.TABLE_DETAIL(table.id));
            },
          })
        }
        isCreating={create.isPending}
        error={create.error}
      />

      {importing && (
        <ImportCsvDialog
          key={importing.table.id}
          tableId={importing.table.id}
          columns={importing.table.columns}
          preset={importing.preset}
          open
          onOpenChange={() => {
            setImporting(null);
            router.push(ROUTES.TABLE_DETAIL(importing.table.id));
          }}
        />
      )}
    </div>
  );
}
