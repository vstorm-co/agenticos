"use client";

import { use, useState } from "react";
import { useTranslations } from "next-intl";
import { Settings2, Share2 } from "lucide-react";

import { PageHeader } from "@/components/dashboard/page-header";
import { SharingPanel } from "@/components/sharing/sharing-panel";
import { HasMorePager } from "@/components/tables/has-more-pager";
import { RecordDetailSheet } from "@/components/tables/record-detail-sheet";
import { SchemaEditorDialog } from "@/components/tables/schema-editor-dialog";
import { TableGridView } from "@/components/tables/table-grid-view";
import { TableKanbanView } from "@/components/tables/table-kanban-view";
import { TableListView } from "@/components/tables/table-list-view";
import { ViewSelect } from "@/components/tables/view-select";
import {
  Badge,
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  Tabs,
  TabsList,
  TabsTrigger,
  PAGE_SIZE,
} from "@/components/ui";
import { LoadingState, ErrorState } from "@/components/states";
import { useTable, useTableRecords, useTableViews } from "@/hooks";
import { DIALOG_FORM, DIALOG_SCROLL } from "@/lib/dialog-sizes";
import { useUrlState } from "@/hooks/use-url-state";
import { emptyViewConfig } from "@/types/tables";
import type { RecordFilter, RecordRead, RecordSort, ViewKind } from "@/types/tables";

function parseTab(value: string | null): ViewKind {
  return value === "kanban" || value === "list" ? value : "table";
}

export default function TableDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const t = useTranslations("pages.tables.detail");

  const [tabParam, setTabParam] = useUrlState("view");
  const tab = parseTab(tabParam);
  const setTab = (next: ViewKind) => setTabParam(next === "table" ? null : next);
  const [viewIdParam, setViewIdParam] = useUrlState("viewId");

  const { table, isLoading, error, changeSchema, invalidate: refreshTable } = useTable(id);
  const {
    views,
    create: createView,
    update: updateView,
    remove: removeView,
  } = useTableViews(id, tab);

  const [schemaOpen, setSchemaOpen] = useState(false);
  const [shareOpen, setShareOpen] = useState(false);
  const [openRecord, setOpenRecord] = useState<RecordRead | null>(null);
  const [page, setPage] = useState(0);
  const DEFAULT_SORT: RecordSort = { by: "created_at", direction: "asc" };
  const [sort, setSort] = useState<RecordSort>(DEFAULT_SORT);

  const activeView = views.find((view) => view.id === viewIdParam) ?? null;
  const filters: RecordFilter[] = activeView?.config.filters ?? [];
  const groupBy = activeView?.config.group_by ?? null;

  // `sort` is the grid's own working sort, seeded from the active view's
  // stored one each time the view changes - re-seeded from render, not a
  // `useEffect`, so switching views never paints one frame of the old sort
  // first. Reading `activeView.config.sort` directly here instead would work
  // for display but not for clicking a header: `onSort` below only knows how
  // to update this local state, and a saved sort a click could never
  // override reads as a sortable column that silently ignores every click.
  const [seenViewKey, setSeenViewKey] = useState(activeView?.id);
  if (activeView?.id !== seenViewKey) {
    setSeenViewKey(activeView?.id);
    setSort(activeView?.config.sort ?? DEFAULT_SORT);
  }

  // Reset to the first page whenever the active view, tab, filters or sort
  // changes - otherwise a page advanced under one view carries over as the
  // offset for the next query, which can land past the end of a smaller
  // result and render the empty-record state even though matching records
  // exist earlier in it. Re-seeded from render, the same pattern as `sort`
  // above, so switching never paints one frame of the stale page first.
  const recordsKey = JSON.stringify({ tab, viewId: viewIdParam, filters, sort });
  const [seenRecordsKey, setSeenRecordsKey] = useState(recordsKey);
  if (recordsKey !== seenRecordsKey) {
    setSeenRecordsKey(recordsKey);
    setPage(0);
  }

  const {
    records,
    hasMore,
    isLoading: recordsLoading,
    isPlaceholderData: recordsPlaceholder,
  } = useTableRecords(tab === "kanban" ? null : id, {
    filters,
    sort,
    skip: page * PAGE_SIZE,
    limit: PAGE_SIZE,
  });

  if (isLoading) return <LoadingState variant="skeleton-panel" rows={3} />;
  if (error || !table) return <ErrorState />;

  const canEdit = table.can_edit;
  const visibleColumns = activeView?.config.visible_columns;
  const columns = table.columns.filter(
    (column) =>
      !column.archived &&
      (visibleColumns === null ||
        visibleColumns === undefined ||
        visibleColumns.includes(column.id)),
  );

  return (
    <div>
      <PageHeader
        title={table.name}
        description={table.description ?? undefined}
        actions={
          <div className="flex items-center gap-2">
            <Badge variant="outline">{t(`visibility.${table.visibility}`)}</Badge>
            {canEdit && (
              <Button
                variant="outline"
                size="sm"
                data-tour="table-columns"
                onClick={() => {
                  // The last save's refusal is not about this editing session.
                  changeSchema.reset();
                  setSchemaOpen(true);
                }}
              >
                <Settings2 className="h-4 w-4" /> {t("columns")}
              </Button>
            )}
            <Button variant="outline" size="sm" onClick={() => setShareOpen(true)}>
              <Share2 className="h-4 w-4" /> {t("share")}
            </Button>
          </div>
        }
      />

      <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
        <Tabs value={tab} onValueChange={(next) => setTab(next as ViewKind)}>
          <TabsList data-tour="table-view-tabs">
            <TabsTrigger value="table">{t("tabs.table")}</TabsTrigger>
            <TabsTrigger value="kanban">{t("tabs.kanban")}</TabsTrigger>
            <TabsTrigger value="list">{t("tabs.list")}</TabsTrigger>
          </TabsList>
        </Tabs>
        <ViewSelect
          kind={tab}
          views={views}
          activeViewId={viewIdParam}
          onSelect={setViewIdParam}
          canCreate={canEdit}
          onCreate={async (name, visibility) => {
            const created = await createView.mutateAsync({
              name,
              kind: tab,
              visibility,
              config: emptyViewConfig(),
            });
            setViewIdParam(created.id);
          }}
          onRename={(viewId, name) => updateView.mutateAsync({ viewId, data: { name } })}
          onDelete={(viewId) =>
            // Deselected only once it is gone: a refused delete (toasted by the
            // hook) leaves the view in place and still selected.
            removeView.mutateAsync(viewId).then(
              () => {
                if (viewId === viewIdParam) setViewIdParam(null);
              },
              () => undefined,
            )
          }
        />
      </div>

      {tab === "table" && (
        <>
          <TableGridView
            columns={columns}
            records={records}
            isLoading={recordsLoading}
            sort={sort}
            onSort={setSort}
            onOpenRecord={setOpenRecord}
          />
          <div className="mt-3">
            <HasMorePager
              page={page}
              hasMore={hasMore}
              // The previous page stands in while the next one loads; its
              // `has_more` says nothing about the page being fetched.
              isLoading={recordsLoading || recordsPlaceholder}
              onPage={setPage}
            />
          </div>
        </>
      )}

      {tab === "kanban" &&
        (groupBy ? (
          <TableKanbanView
            tableId={id}
            columns={table.columns}
            groupByColumnId={groupBy}
            baseFilters={filters}
            sort={sort}
            onOpenRecord={setOpenRecord}
            canEdit={canEdit}
          />
        ) : (
          <p className="text-muted-foreground text-sm">{t("kanbanNeedsView")}</p>
        ))}

      {tab === "list" && (
        <>
          <TableListView
            columns={columns}
            records={records}
            isLoading={recordsLoading}
            onOpenRecord={setOpenRecord}
          />
          <div className="mt-3">
            <HasMorePager
              page={page}
              hasMore={hasMore}
              isLoading={recordsLoading || recordsPlaceholder}
              onPage={setPage}
            />
          </div>
        </>
      )}

      <RecordDetailSheet
        tableId={id}
        columns={table.columns}
        record={openRecord}
        open={!!openRecord}
        onOpenChange={(open) => !open && setOpenRecord(null)}
        canEdit={canEdit}
        // Advances the open record only. A commit that lands after the sheet
        // closed must not reopen it, nor swap in a different record - nor
        // step it back: a reload read before a write landed answers after it.
        onRecordUpdated={(updated) =>
          setOpenRecord((current) =>
            current?.id === updated.id && updated.revision >= current.revision ? updated : current,
          )
        }
      />

      {canEdit && (
        <SchemaEditorDialog
          open={schemaOpen}
          onOpenChange={setSchemaOpen}
          table={table}
          onSave={(cols) =>
            changeSchema.mutate(
              { expected_version: table.schema_version, columns: cols },
              { onSuccess: () => setSchemaOpen(false) },
            )
          }
          isSaving={changeSchema.isPending}
          error={changeSchema.error}
        />
      )}

      <Dialog
        open={shareOpen}
        onOpenChange={(open) => {
          setShareOpen(open);
          // A visibility change there is this table's own field: the badge
          // above and the catalog both read it.
          if (!open) void refreshTable();
        }}
      >
        <DialogContent className={`${DIALOG_SCROLL} ${DIALOG_FORM}`}>
          <DialogHeader>
            <DialogTitle>{t("shareTitle", { name: table.name })}</DialogTitle>
            <DialogDescription>{t("shareDescription")}</DialogDescription>
          </DialogHeader>
          <SharingPanel resourceType="table" resourceId={id} canManage={canEdit} />
        </DialogContent>
      </Dialog>
    </div>
  );
}
