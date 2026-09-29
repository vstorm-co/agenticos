"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Plus, Workflow } from "lucide-react";
import { useTranslations } from "next-intl";

import { PageHeader } from "@/components/dashboard/page-header";
import {
  Button,
  ListCard,
  ListCardEmpty,
  Pager,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  useListControls,
} from "@/components/ui";
import { WorkflowCard } from "@/components/workflows/workflow-card";
import { WorkflowCreateDialog } from "@/components/workflows/workflow-create-dialog";
import type { WorkflowCreateChoice } from "@/components/workflows/workflow-create-dialog";
import { usePermissions, useWorkflows } from "@/hooks";
import { ROUTES } from "@/lib/constants";
import { Perm } from "@/types/permissions";
import type { WorkflowRead, WorkflowStatus } from "@/lib/workflows/types";

type Filter = "all" | WorkflowStatus;

const FILTERS: readonly Filter[] = ["all", "draft", "published", "archived"];

/**
 * The workflows list — draft / published / archived, like the agents list.
 *
 * Lists what the caller can see, filters by status, and offers a permission-gated
 * create (blank canvas or a template) and per-row duplicate. Both creation paths
 * seed a new workflow's draft and route straight into the editor.
 */
export default function WorkflowsPage() {
  const t = useTranslations("pages.workflows");
  const router = useRouter();
  const { can } = usePermissions();
  const canCreate = can(Perm.workflowsCreate);
  // Gate the list query so a caller without workflows:view never hits the network
  // for a list a refusal would answer — not fetched, not a 403 in the log (#1787 F3).
  const { workflows, isLoading, create, duplicate } = useWorkflows({
    enabled: can(Perm.workflowsView),
  });

  const [filter, setFilter] = useState<Filter>("all");
  const [createOpen, setCreateOpen] = useState(false);

  // Status filter and paging both run over the *whole* registry the hook walked,
  // so a status still matches a workflow on what would have been a later page
  // (#1787). The status rides the controls' query — "all" is the empty query
  // that filters nothing — and `matches` compares it to a row's own status.
  const list = useListControls({
    items: workflows,
    query: filter === "all" ? "" : filter,
    matches: (workflow, status) => workflow.status === status,
  });
  const filtersActive = filter !== "all";

  const onFilter = (value: Filter) => {
    setFilter(value);
    list.setPage(0);
  };

  const onChoose = (choice: WorkflowCreateChoice) =>
    create.mutate(
      { name: choice.name, graph: choice.graph },
      {
        onSuccess: (workflow) => {
          setCreateOpen(false);
          router.push(ROUTES.WORKFLOW_DETAIL(workflow.id));
        },
      },
    );

  const onDuplicate = (workflow: WorkflowRead) =>
    duplicate.mutate(
      { sourceId: workflow.id, name: t("copyOfName", { name: workflow.name }) },
      { onSuccess: (created) => router.push(ROUTES.WORKFLOW_DETAIL(created.id)) },
    );

  const statusControls = (
    <Select value={filter} onValueChange={(value) => onFilter(value as Filter)}>
      <SelectTrigger data-tour="workflows-list" className="w-40" aria-label={t("filterByStatus")}>
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
  );

  return (
    <div className="space-y-6">
      <PageHeader
        title={t("title")}
        description={t("description")}
        actions={
          canCreate ? (
            <Button
              onClick={() => setCreateOpen(true)}
              disabled={create.isPending}
              data-tour="workflows-new"
            >
              <Plus className="h-4 w-4" />
              {t("newWorkflow")}
            </Button>
          ) : undefined
        }
      />

      <ListCard
        title={t("catalog")}
        counted={
          isLoading
            ? null
            : list.matched === list.total
              ? t("shownCount", { count: list.total })
              : t("shownOfTotal", { visible: list.matched, total: list.total })
        }
        controls={statusControls}
      >
        {list.matched === 0 ? (
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
            cta={
              filtersActive
                ? { label: t("clearFilter"), onClick: () => onFilter("all") }
                : undefined
            }
          />
        ) : (
          <div className="space-y-4">
            <div className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3">
              {list.visible.map((workflow) => (
                <WorkflowCard
                  key={workflow.id}
                  workflow={workflow}
                  canCreate={canCreate}
                  busy={duplicate.isPending && duplicate.variables?.sourceId === workflow.id}
                  onDuplicate={() => onDuplicate(workflow)}
                />
              ))}
            </div>
            <Pager
              page={list.page}
              pageCount={list.pageCount}
              matched={list.matched}
              total={list.total}
              onPage={list.setPage}
              counted={t("shownCount", { count: list.total })}
            />
          </div>
        )}
      </ListCard>

      <WorkflowCreateDialog
        open={createOpen}
        onOpenChange={setCreateOpen}
        onChoose={onChoose}
        busy={create.isPending}
      />
    </div>
  );
}
