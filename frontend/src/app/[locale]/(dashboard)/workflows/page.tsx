"use client";

import { useWorkspaceFullscreen } from "@/hooks/use-workspace-fullscreen";
import { WorkspaceFullscreenButton } from "@/components/ui/workspace-fullscreen-button";
import { useMemo, useState } from "react";
import { ListFilters } from "@/components/ui/list-filters";
import { useRouter } from "next/navigation";
import Link from "next/link";
import { Activity, Library, Plus, Upload, Workflow } from "lucide-react";
import { useTranslations } from "next-intl";

import { ErrorState } from "@/components/states";
import { PageHeader } from "@/components/dashboard/page-header";
import {
  Button,
  ListCard,
  ListCardEmpty,
  Pager,
  SearchInput,
  Skeleton,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  useListControls,
} from "@/components/ui";
import { WorkflowCard } from "@/components/workflows/workflow-card";
import { ImportWorkflowDialog } from "@/components/workflows/import-dialog";
import { WorkflowTemplateDialog } from "@/components/workflows/workflow-template-dialog";
import { WorkflowCreateDialog } from "@/components/workflows/workflow-create-dialog";
import type { WorkflowCreateChoice } from "@/components/workflows/workflow-create-dialog";
import { useNodeCatalog, usePermissions, useWorkflowActions, useWorkflows } from "@/hooks";
import { useUrlState } from "@/hooks/use-url-state";
import { ROUTES } from "@/lib/constants";
import { Perm } from "@/types/permissions";
import type { WorkflowRead, WorkflowStatus } from "@/lib/workflows/types";

type Filter = "all" | WorkflowStatus;
type Sort = "edited" | "name" | "created";

const FILTERS: readonly Filter[] = ["all", "draft", "published", "archived"];
const SORTS: readonly Sort[] = ["edited", "name", "created"];
const ALL_TAGS = "__all__";

function parseFilter(value: string | null): Filter {
  return FILTERS.includes(value as Filter) ? (value as Filter) : "all";
}

function parseSort(value: string | null): Sort {
  return SORTS.includes(value as Sort) ? (value as Sort) : "edited";
}

/** Newest first for the two times, A to Z for the name. */
function compare(sort: Sort): (a: WorkflowRead, b: WorkflowRead) => number {
  if (sort === "name") return (a, b) => a.name.localeCompare(b.name);
  const at = (workflow: WorkflowRead) =>
    (sort === "created" ? workflow.created_at : (workflow.updated_at ?? workflow.created_at)) ?? "";
  return (a, b) => at(b).localeCompare(at(a));
}

/**
 * The workflows list — draft / published / archived, like the agents list.
 *
 * Lists what the caller can see, filters by status, and offers a permission-gated
 * create (blank canvas or a template) and per-row duplicate. Both creation paths
 * seed a new workflow's draft and route straight into the editor.
 */
export default function WorkflowsPage() {
  const {
    ref: galleryRef,
    expanded: galleryFullscreen,
    toggle: toggleGalleryFullscreen,
  } = useWorkspaceFullscreen();
  const t = useTranslations("pages.workflows");
  const router = useRouter();
  const tc = useTranslations("common");
  const { can, isLoading: permissionsLoading } = usePermissions();
  const canCreate = can(Perm.workflowsCreate);
  // Gate the list query so a caller without workflows:view never hits the network
  // for a list a refusal would answer — not fetched, not a 403 in the log (#1787 F3).
  const { nodes: catalog } = useNodeCatalog();
  const { workflows, isLoading, error, refetch, create, duplicate } = useWorkflows({
    enabled: can(Perm.workflowsView),
  });

  const loading = isLoading || permissionsLoading;
  const actions = useWorkflowActions();
  const canEdit = can(Perm.workflowsEdit);

  // Kept in the URL, so a reload - or a link someone was sent - shows the same list.
  const [filterParam, setFilterParam] = useUrlState("status");
  const [sortParam, setSortParam] = useUrlState("sort");
  const [tagParam, setTagParam] = useUrlState("tag");
  const [queryParam, setQueryParam] = useUrlState("q");
  const filter = parseFilter(filterParam);
  const sort = parseSort(sortParam);
  const [createOpen, setCreateOpen] = useState(false);
  const [templatesOpen, setTemplatesOpen] = useState(false);
  const [initial, setInitial] = useState<WorkflowCreateChoice>();
  const [importOpen, setImportOpen] = useState(false);

  const tags = useMemo(
    () => [...new Set(workflows.flatMap((workflow) => workflow.tags))].sort(),
    [workflows],
  );
  // Status and tag narrow the list before the search does; the order is applied last.
  const narrowed = useMemo(
    () =>
      workflows
        .filter((workflow) => filter === "all" || workflow.status === filter)
        .filter((workflow) => tagParam === null || workflow.tags.includes(tagParam))
        .sort(compare(sort)),
    [workflows, filter, tagParam, sort],
  );

  // Search and paging both run over the *whole* registry the hook walked, so a
  // search still finds a workflow on what would have been a later page (#1787).
  const list = useListControls({
    items: narrowed,
    query: queryParam ?? "",
    onQueryChange: (next) => setQueryParam(next === "" ? null : next),
    matches: (workflow, needle) =>
      workflow.name.toLowerCase().includes(needle) ||
      (workflow.description ?? "").toLowerCase().includes(needle) ||
      workflow.tags.some((tag) => tag.includes(needle)),
  });
  const filtersActive = filter !== "all" || tagParam !== null || (queryParam ?? "") !== "";

  const onFilter = (value: Filter) => {
    setFilterParam(value === "all" ? null : value);
    list.setPage(0);
  };
  const clearFilters = () => {
    setFilterParam(null);
    setTagParam(null);
    setQueryParam(null);
    list.setPage(0);
  };

  const onChoose = (choice: WorkflowCreateChoice) =>
    create.mutate(choice, {
      onSuccess: (workflow) => {
        setCreateOpen(false);
        router.push(ROUTES.WORKFLOW_DETAIL(workflow.id));
      },
    });

  const onDuplicate = (workflow: WorkflowRead) =>
    duplicate.mutate(
      { sourceId: workflow.id, name: t("copyOfName", { name: workflow.name }) },
      { onSuccess: (created) => router.push(ROUTES.WORKFLOW_DETAIL(created.id)) },
    );

  const statusControls = (
    <div data-tour="workflows-list" className="flex min-w-0 flex-wrap items-center gap-2">
      <SearchInput
        className="min-w-0 flex-1 sm:flex-none"
        value={queryParam ?? ""}
        onChange={(next) => {
          setQueryParam(next === "" ? null : next);
          list.setPage(0);
        }}
        placeholder={t("searchPlaceholder")}
      />
      <ListFilters
        compact
        active={Number(filter !== "all") + Number(tagParam !== null) + Number(sort !== "edited")}
      >
        <Select value={filter} onValueChange={(value) => onFilter(value as Filter)}>
          <SelectTrigger className="w-36" aria-label={t("filterByStatus")}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {FILTERS.map((value) => (
              <SelectItem key={value} value={value}>
                {t(`filter.${value}`)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        {tags.length > 0 && (
          <Select
            value={tagParam ?? ALL_TAGS}
            onValueChange={(value) => {
              setTagParam(value === ALL_TAGS ? null : value);
              list.setPage(0);
            }}
          >
            <SelectTrigger className="w-36" aria-label={t("filterByTag")}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={ALL_TAGS}>{t("allTags")}</SelectItem>
              {tags.map((tag) => (
                <SelectItem key={tag} value={tag}>
                  {tag}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
        <Select
          value={sort}
          onValueChange={(value) => setSortParam(value === "edited" ? null : value)}
        >
          <SelectTrigger className="w-40" aria-label={t("sortBy")}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {SORTS.map((value) => (
              <SelectItem key={value} value={value}>
                {t(`sort.${value}`)}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </ListFilters>
    </div>
  );

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-6">
      <PageHeader
        title={t("title")}
        description={t("description")}
        actions={
          <>
            <Button variant="outline" asChild>
              <Link href={ROUTES.WORKFLOW_ALL_RUNS}>
                <Activity className="h-4 w-4" />
                {t("allRuns")}
              </Link>
            </Button>
            {canCreate && (
              <Button variant="outline" onClick={() => setImportOpen(true)}>
                <Upload className="h-4 w-4" />
                {t("importWorkflow")}
              </Button>
            )}
            {canCreate && (
              <Button
                variant="outline"
                onClick={() => setTemplatesOpen(true)}
                disabled={create.isPending}
              >
                <Library className="size-4" />
                {t("templateLibrary")}
              </Button>
            )}
            {canCreate && (
              <Button
                onClick={() => {
                  setInitial(undefined);
                  setCreateOpen(true);
                }}
                disabled={create.isPending}
                data-tour="workflows-new"
              >
                <Plus className="h-4 w-4" />
                {t("newWorkflow")}
              </Button>
            )}
          </>
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
        counted={
          loading
            ? null
            : list.matched === list.total
              ? t("shownCount", { count: list.total })
              : t("shownOfTotal", { visible: list.matched, total: list.total })
        }
        controls={
          <div className="flex flex-wrap items-center gap-2">
            {statusControls}
            <WorkspaceFullscreenButton
              expanded={galleryFullscreen}
              onToggle={toggleGalleryFullscreen}
            />
          </div>
        }
      >
        {loading ? (
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {[0, 1, 2].map((row) => (
              <Skeleton key={row} className="h-44 rounded-xl" />
            ))}
          </div>
        ) : error && workflows.length === 0 ? (
          <ErrorState cta={{ label: tc("retry"), onClick: () => void refetch() }} />
        ) : list.matched === 0 ? (
          <ListCardEmpty
            icon={Workflow}
            title={filtersActive ? t("nothingMatches") : t("noWorkflowsYet")}
            description={
              filtersActive
                ? t("noWorkflowHereMatches")
                : canCreate
                  ? t("createFirst")
                  : t("nobodyHasShared")
            }
            cta={filtersActive ? { label: t("clearFilter"), onClick: clearFilters } : undefined}
          />
        ) : (
          <div className="space-y-4">
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
              {list.visible.map((workflow) => (
                <WorkflowCard
                  key={workflow.id}
                  workflow={workflow}
                  startsFrom={
                    catalog.find((entry) => entry.id === workflow.entry_node)?.name ?? null
                  }
                  canCreate={canCreate}
                  canEdit={canEdit}
                  busy={duplicate.isPending && duplicate.variables?.sourceId === workflow.id}
                  onDuplicate={() => onDuplicate(workflow)}
                  onArchive={() => actions.archive.mutate(workflow.id)}
                  onRestore={() => actions.unarchive.mutate(workflow.id)}
                  onDelete={() => actions.remove.mutateAsync(workflow.id)}
                />
              ))}
            </div>
            {list.pageCount > 1 && (
              <Pager
                page={list.page}
                pageCount={list.pageCount}
                matched={list.matched}
                total={list.total}
                onPage={list.setPage}
                counted={t("shownCount", { count: list.total })}
              />
            )}
          </div>
        )}
      </ListCard>

      <ImportWorkflowDialog open={importOpen} onOpenChange={setImportOpen} />
      <WorkflowTemplateDialog
        open={templatesOpen}
        onOpenChange={setTemplatesOpen}
        canProvisionTables={can(Perm.tablesCreate) && can(Perm.tablesView) && can(Perm.tablesEdit)}
        onChoose={(choice) => {
          setInitial(choice);
          setTemplatesOpen(false);
          setCreateOpen(true);
        }}
      />
      <WorkflowCreateDialog
        key={`${createOpen}-${initial?.name ?? "blank"}`}
        initial={initial}
        open={createOpen}
        onOpenChange={setCreateOpen}
        onChoose={onChoose}
        busy={create.isPending}
      />
    </div>
  );
}
