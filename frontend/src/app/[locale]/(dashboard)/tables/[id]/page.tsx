"use client";

import { use, useState } from "react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import {
  Building2,
  Download,
  Lock,
  MoreHorizontal,
  Plus,
  Save,
  Settings2,
  Share2,
  Upload,
  Users,
  Zap,
} from "lucide-react";

import { PageHeader } from "@/components/dashboard/page-header";
import { getErrorMessage, schemaDependents } from "@/lib/api-error";
import { ROUTES } from "@/lib/constants";
import { SharingPanel } from "@/components/sharing/sharing-panel";
import { HasMorePager } from "@/components/tables/has-more-pager";
import { NewRecordDialog } from "@/components/tables/new-record-dialog";
import { ImportCsvDialog } from "@/components/tables/import-csv-dialog";
import { exportRecords } from "@/lib/tables-api";
import {
  AddColumnDialog,
  RenameColumnDialog,
  currentColumns,
} from "@/components/tables/column-dialogs";
import type { ColumnActions } from "@/components/tables/column-header-menu";
import { HiddenColumnsPopover } from "@/components/tables/hidden-columns-popover";
import { RecordDetailSheet } from "@/components/tables/record-detail-sheet";
import { isComplete } from "@/components/tables/record-filters";
import { RecordFiltersPopover } from "@/components/tables/record-filters-popover";
import { SchemaDependents } from "@/components/tables/schema-dependents";
import { SchemaEditorDialog } from "@/components/tables/schema-editor-dialog";
import { TableGridView } from "@/components/tables/table-grid-view";
import { TableKanbanView } from "@/components/tables/table-kanban-view";
import { TableListView } from "@/components/tables/table-list-view";
import { TableTriggersPanel } from "@/components/tables/triggers/table-triggers-panel";
import { ViewSelect } from "@/components/tables/view-select";
import {
  Button,
  ConfirmDialog,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  Sheet,
  SheetClose,
  SheetContent,
  SheetHeader,
  SheetTitle,
  Tabs,
  TabsList,
  TabsTrigger,
  PAGE_SIZE,
  SearchInput,
  useDebounced,
} from "@/components/ui";
import { LoadingState, ErrorState } from "@/components/states";
import {
  useTable,
  useTableRecordCount,
  useTableRecordPages,
  useTableRecords,
  useTableViews,
} from "@/hooks";
import { DIALOG_FORM, DIALOG_SCROLL } from "@/lib/dialog-sizes";
import { useUrlState } from "@/hooks/use-url-state";
import { emptyViewConfig } from "@/types/tables";
import type {
  CellValue,
  ColumnDef,
  ColumnInput,
  RecordFilter,
  TableRead,
  RecordRead,
  RecordSort,
  ViewKind,
} from "@/types/tables";

const VISIBILITY_ICON = { private: Lock, team: Users, org: Building2 } as const;

function parseTab(value: string | null): ViewKind {
  return value === "kanban" || value === "list" ? value : "table";
}

export default function TableDetailPage({ params }: { params: Promise<{ id: string }> }) {
  const { id } = use(params);
  const t = useTranslations("pages.tables.detail");
  const tp = useTranslations("pages.tables");
  const tTriggers = useTranslations("pages.tables.triggers");
  const tErrors = useTranslations("errors");
  const tMenu = useTranslations("tables.columnMenu");

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
  const [triggersOpen, setTriggersOpen] = useState(false);
  // What the Add record form opens with - null while it is closed. Each opening
  // mounts the form afresh, so what it starts from is read then.
  const [addingRecord, setAddingRecord] = useState<Record<string, CellValue> | null>(null);
  const [addCount, setAddCount] = useState(0);
  const addRecord = (initial: Record<string, CellValue> = {}) => {
    setAddCount(addCount + 1);
    setAddingRecord(initial);
  };
  const [addingColumn, setAddingColumn] = useState(false);
  const [importing, setImporting] = useState(false);
  const [exporting, setExporting] = useState(false);
  const [renaming, setRenaming] = useState<ColumnDef | null>(null);
  const [archiving, setArchiving] = useState<ColumnDef | null>(null);
  const [openRecord, setOpenRecord] = useState<RecordRead | null>(null);
  const [page, setPage] = useState(0);
  const DEFAULT_SORT: RecordSort = { by: "created_at", direction: "asc" };
  const activeView = views.find((view) => view.id === viewIdParam) ?? null;
  const [sort, setSort] = useState<RecordSort>(activeView?.config.sort ?? DEFAULT_SORT);
  const [filters, setFilters] = useState<RecordFilter[]>(activeView?.config.filters ?? []);
  const [searchDraft, setSearchDraft] = useState(activeView?.config.search ?? "");
  const [visible, setVisible] = useState<string[] | null>(
    activeView?.config.visible_columns ?? null,
  );
  const search = useDebounced(searchDraft).trim() || null;
  // A board groups by its view's column, or - with no view saying so - by the
  // column picked above it, so a board is one choice away rather than a dead end.
  const [groupPick, setGroupPick] = useState<string | null>(null);
  const groupBy = activeView?.config.group_by ?? groupPick;

  // `sort` is the grid's own working sort, seeded from the active view's
  // stored one each time the view changes - re-seeded from render, not a
  // `useEffect`, so switching views never paints one frame of the old sort
  // first. Reading `activeView.config.sort` directly here instead would work
  // for display but not for clicking a header: `onSort` below only knows how
  // to update this local state, and a saved sort a click could never
  // override reads as a sortable column that silently ignores every click.
  // The filters, the search and the hidden columns are seeded the same way,
  // and for the same reason: they change here, and are saved to the view.
  const [seenViewKey, setSeenViewKey] = useState(activeView?.id);
  if (activeView?.id !== seenViewKey) {
    setSeenViewKey(activeView?.id);
    setSort(activeView?.config.sort ?? DEFAULT_SORT);
    setFilters(activeView?.config.filters ?? []);
    setSearchDraft(activeView?.config.search ?? "");
    setVisible(activeView?.config.visible_columns ?? null);
  }

  // A condition still being written narrows nothing yet.
  const applied = filters.filter(isComplete);

  // Reset to the first page whenever the active view, tab, filters or sort
  // changes - otherwise a page advanced under one view carries over as the
  // offset for the next query, which can land past the end of a smaller
  // result and render the empty-record state even though matching records
  // exist earlier in it. Re-seeded from render, the same pattern as `sort`
  // above, so switching never paints one frame of the stale page first.
  const recordsKey = JSON.stringify({ tab, viewId: viewIdParam, applied, search, sort });
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
  } = useTableRecords(tab === "list" ? id : null, {
    filters: applied,
    search,
    sort,
    skip: page * PAGE_SIZE,
    limit: PAGE_SIZE,
  });
  // The grid scrolls rather than pages: its records load as it nears the end.
  const grid = useTableRecordPages(tab === "table" ? id : null, {
    filters: applied,
    search,
    sort,
  });
  const matching = useTableRecordCount(id, { filters: applied, search });

  if (isLoading) return <LoadingState variant="skeleton-panel" rows={3} />;
  if (error || !table) return <ErrorState />;

  const canEdit = table.can_edit;
  const liveColumns = table.columns.filter((column) => !column.archived);
  const columns = liveColumns.filter((column) => visible === null || visible.includes(column.id));
  const hidden = liveColumns.filter((column) => !columns.includes(column));
  // What this screen shows now, against what the active view keeps.
  const working = { filters: applied, search, sort, visible_columns: visible };
  const groupable = liveColumns.filter((column) => column.type === "single_select");
  const VisibilityIcon = VISIBILITY_ICON[table.visibility];
  const unsaved =
    activeView !== null &&
    activeView.can_manage &&
    JSON.stringify(working) !==
      JSON.stringify({
        filters: activeView.config.filters,
        search: activeView.config.search ?? null,
        sort: activeView.config.sort,
        visible_columns: activeView.config.visible_columns,
      });

  /** Save what the screen shows - its records, in its order, its columns - as a CSV file. */
  const exportShown = () => {
    setExporting(true);
    exportRecords(id, {
      filters: applied,
      search,
      sort,
      columns: columns.map((column) => column.id),
    })
      .catch((failure: unknown) => toast.error(getErrorMessage(failure, tErrors)))
      .finally(() => setExporting(false));
  };

  /** Show or hide one column on this screen; showing every live one again is `null`. */
  const setShown = (columnId: string, shown: boolean) => {
    const current = visible ?? liveColumns.map((column) => column.id);
    const next = shown
      ? liveColumns
          .map((column) => column.id)
          .filter((id) => id === columnId || current.includes(id))
      : current.filter((id) => id !== columnId);
    setVisible(next.length === liveColumns.length ? null : next);
  };

  /** Write the whole column list as one schema version, as the Columns dialog does. */
  const saveColumns = (next: ColumnInput[], onSaved: (saved: TableRead) => void) =>
    changeSchema.mutate(
      { expected_version: table.schema_version, columns: next },
      {
        onSuccess: onSaved,
        // Only archiving can be refused for what still uses a column, and the
        // archive dialog lists that in place of a toast that names nothing.
        onError: (failure) => {
          if (schemaDependents(failure) === null) toast.error(getErrorMessage(failure, tErrors));
        },
      },
    );
  const columnActions: ColumnActions = {
    onSort: setSort,
    onRename: setRenaming,
    onHide: (column) => setShown(column.id, false),
    onArchive: (column) => {
      // A refusal from the last archive belongs to that column, not this one.
      changeSchema.reset();
      setArchiving(column);
    },
  };

  return (
    <div>
      <PageHeader
        title={table.name}
        description={table.description ?? undefined}
        breadcrumbs={[{ label: tp("title"), href: ROUTES.TABLES }, { label: table.name }]}
        // Facts about the table, under its name rather than among the controls.
        badges={
          <span className="text-muted-foreground inline-flex items-center gap-1.5 text-xs">
            <VisibilityIcon aria-hidden="true" className="size-3.5" />
            {t(`visibility.${table.visibility}`)}
            {matching && (
              <>
                <span aria-hidden="true">·</span>
                <span className="tabular-nums">
                  {t(matching.capped ? "recordCountCapped" : "recordCount", {
                    count: matching.count,
                  })}
                </span>
              </>
            )}
          </span>
        }
        actions={
          <div className="flex items-center gap-2">
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
            <Button
              variant="outline"
              size="sm"
              data-tour="table-triggers"
              onClick={() => setTriggersOpen(true)}
            >
              <Zap className="h-4 w-4" /> {tTriggers("button")}
            </Button>
            <Button variant="outline" size="sm" onClick={() => setShareOpen(true)}>
              <Share2 className="h-4 w-4" /> {t("share")}
            </Button>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="outline" size="sm" aria-label={t("more")} title={t("more")}>
                  <MoreHorizontal className="h-4 w-4" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                {canEdit && (
                  <DropdownMenuItem onSelect={() => setImporting(true)}>
                    <Upload className="h-4 w-4" /> {t("import")}
                  </DropdownMenuItem>
                )}
                <DropdownMenuItem disabled={exporting} onSelect={exportShown}>
                  <Download className="h-4 w-4" /> {t("export")}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
            {canEdit && (
              <Button size="sm" onClick={() => addRecord()}>
                <Plus className="h-4 w-4" /> {t("addRecord")}
              </Button>
            )}
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
        <div className="flex flex-wrap items-center gap-2">
          <SearchInput
            value={searchDraft}
            onChange={setSearchDraft}
            placeholder={t("search")}
            className="sm:w-56"
          />
          <RecordFiltersPopover columns={liveColumns} filters={filters} onChange={setFilters} />
          {hidden.length > 0 && (
            <HiddenColumnsPopover
              hidden={hidden}
              onShow={(column) => setShown(column.id, true)}
              onShowAll={() => setVisible(null)}
            />
          )}
          {unsaved && (
            <Button
              variant="outline"
              size="sm"
              onClick={() =>
                void updateView
                  .mutateAsync({
                    viewId: activeView.id,
                    data: { config: { ...activeView.config, ...working } },
                  })
                  .then(
                    () => toast.success(t("viewSaved")),
                    // The hook leaves a refused update to its caller; there is
                    // no dialog here to show it in.
                    (error: unknown) => toast.error(getErrorMessage(error, tErrors)),
                  )
              }
            >
              <Save className="h-4 w-4" /> {t("saveView")}
            </Button>
          )}
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
                // A new view keeps what the screen is narrowed by now, and a
                // board the column it is grouped by.
                config: {
                  ...emptyViewConfig(),
                  ...working,
                  group_by: tab === "kanban" ? groupBy : null,
                },
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
      </div>

      {tab === "table" && (
        // A bounded height, so the grid scrolls its own rows and draws only those in view.
        <div className="flex h-[calc(100dvh-16rem)] min-h-96 flex-col">
          <TableGridView
            tableId={id}
            canEdit={canEdit}
            onAddRecord={canEdit ? addRecord : undefined}
            columnActions={canEdit ? columnActions : undefined}
            onAddColumn={canEdit ? () => setAddingColumn(true) : undefined}
            columns={columns}
            records={grid.records}
            isLoading={grid.isLoading}
            onEndReached={grid.loadMore}
            sort={sort}
            onSort={setSort}
            onOpenRecord={setOpenRecord}
          />
          {(grid.isFetchingNextPage || grid.truncated) && (
            <p className="text-muted-foreground mt-2 text-center text-xs">
              {grid.isFetchingNextPage ? t("loadingMore") : t("truncated")}
            </p>
          )}
        </div>
      )}

      {tab === "kanban" && groupPick !== null && !activeView?.config.group_by && (
        // Picked here rather than saved: it can be picked again.
        <div className="text-muted-foreground mb-3 flex items-center gap-2 text-sm">
          {t("kanbanGroupBy")}
          <Select value={groupPick} onValueChange={setGroupPick}>
            <SelectTrigger className="h-8 w-44" aria-label={t("kanbanGroupBy")}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              {groupable.map((column) => (
                <SelectItem key={column.id} value={column.id}>
                  {column.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
      )}
      {tab === "kanban" &&
        (groupBy ? (
          <TableKanbanView
            tableId={id}
            columns={table.columns}
            shownColumns={columns}
            groupByColumnId={groupBy}
            baseFilters={applied}
            search={search}
            sort={sort}
            onOpenRecord={setOpenRecord}
            canEdit={canEdit}
          />
        ) : (
          <div className="border-border flex flex-col items-center gap-3 rounded-xl border border-dashed px-6 py-12 text-center">
            <p className="text-sm font-medium">{t("kanbanGroupTitle")}</p>
            {groupable.length > 0 ? (
              <>
                <p className="text-muted-foreground max-w-md text-sm">{t("kanbanGroupHint")}</p>
                <Select value="" onValueChange={setGroupPick}>
                  <SelectTrigger className="w-56" aria-label={t("kanbanGroupBy")}>
                    <SelectValue placeholder={t("kanbanGroupBy")} />
                  </SelectTrigger>
                  <SelectContent>
                    {groupable.map((column) => (
                      <SelectItem key={column.id} value={column.id}>
                        {column.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </>
            ) : (
              <>
                <p className="text-muted-foreground max-w-md text-sm">{t("kanbanNoGroupable")}</p>
                {canEdit && (
                  <Button size="sm" variant="outline" onClick={() => setAddingColumn(true)}>
                    <Plus className="h-4 w-4" /> {t("kanbanAddColumn")}
                  </Button>
                )}
              </>
            )}
          </div>
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
        <>
          <RenameColumnDialog
            column={renaming}
            onOpenChange={(open) => !open && setRenaming(null)}
            isSaving={changeSchema.isPending}
            onRename={(column, label) =>
              saveColumns(
                currentColumns(table.columns).map((input) =>
                  input.id === column.id ? { ...input, label } : input,
                ),
                () => setRenaming(null),
              )
            }
          />
          <AddColumnDialog
            open={addingColumn}
            onOpenChange={setAddingColumn}
            isSaving={changeSchema.isPending}
            onAdd={(column) =>
              saveColumns([...currentColumns(table.columns), column], (saved) => {
                setAddingColumn(false);
                // A column just added is one the person wants to see, even on a
                // screen that shows only some: labels are unique among live columns.
                const added = saved.columns.find(
                  (candidate) => !candidate.archived && candidate.label === column.label,
                );
                if (visible !== null && added) setVisible([...visible, added.id]);
              })
            }
          />
          <ConfirmDialog
            open={archiving !== null}
            onOpenChange={(open) => !open && setArchiving(null)}
            title={tMenu("archiveTitle", { column: archiving?.label ?? "" })}
            description={tMenu("archiveDescription")}
            confirmLabel={tMenu("archive")}
            destructive
            loading={changeSchema.isPending}
            onConfirm={() =>
              saveColumns(
                currentColumns(table.columns).map((input) =>
                  input.id === archiving?.id ? { ...input, archived: true } : input,
                ),
                () => setArchiving(null),
              )
            }
          >
            <SchemaDependents error={changeSchema.error} />
          </ConfirmDialog>
        </>
      )}

      {canEdit && (
        <ImportCsvDialog
          tableId={id}
          columns={liveColumns}
          open={importing}
          onOpenChange={setImporting}
        />
      )}

      {canEdit && (
        <NewRecordDialog
          tableId={id}
          columns={table.columns}
          key={addCount}
          open={addingRecord !== null}
          initial={addingRecord ?? undefined}
          onOpenChange={(open) => {
            if (!open) setAddingRecord(null);
          }}
        />
      )}

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

      <Sheet open={triggersOpen} onOpenChange={setTriggersOpen}>
        <SheetContent side="right" className="w-full sm:w-[28rem]">
          <SheetHeader>
            <SheetTitle>{tTriggers("sheetTitle")}</SheetTitle>
            <SheetClose onClick={() => setTriggersOpen(false)} />
          </SheetHeader>
          <div className="overflow-y-auto p-4">
            <TableTriggersPanel tableId={id} columns={table.columns} canEdit={canEdit} />
          </div>
        </SheetContent>
      </Sheet>

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
