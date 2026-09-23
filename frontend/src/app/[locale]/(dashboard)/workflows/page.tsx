"use client";

import { useMemo, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Copy, Plus, Workflow } from "lucide-react";
import { useTranslations } from "next-intl";

import { PageHeader } from "@/components/dashboard/page-header";
import {
  Badge,
  Button,
  ListCard,
  ListCardEmpty,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { WorkflowCreateDialog } from "@/components/workflows/workflow-create-dialog";
import type { WorkflowCreateChoice } from "@/components/workflows/workflow-create-dialog";
import { usePermissions, useWorkflows } from "@/hooks";
import { ROUTES } from "@/lib/constants";
import { Perm } from "@/types/permissions";
import type { WorkflowRead, WorkflowStatus } from "@/lib/workflows/types";

type Filter = "all" | WorkflowStatus;

const FILTERS: readonly Filter[] = ["all", "draft", "published", "archived"];

/** The badge tint per status — draft muted, published affirmative, archived quiet. */
const STATUS_VARIANT: Record<string, "secondary" | "default" | "outline"> = {
  draft: "secondary",
  published: "default",
  archived: "outline",
};

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
  const { workflows, total, isLoading, create, duplicate } = useWorkflows();
  const { can } = usePermissions();
  const canCreate = can(Perm.workflowsCreate);

  const [filter, setFilter] = useState<Filter>("all");
  const [createOpen, setCreateOpen] = useState(false);

  const visible = useMemo(
    () => workflows.filter((workflow) => filter === "all" || workflow.status === filter),
    [workflows, filter],
  );
  const filtersActive = filter !== "all";

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
    <Select value={filter} onValueChange={(value) => setFilter(value as Filter)}>
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
            : visible.length === total
              ? t("shownCount", { count: total })
              : t("shownOfTotal", { visible: visible.length, total })
        }
        controls={statusControls}
      >
        {visible.length === 0 ? (
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
                ? { label: t("clearFilter"), onClick: () => setFilter("all") }
                : undefined
            }
          />
        ) : (
          <ul className="divide-border divide-y">
            {visible.map((workflow) => (
              <li key={workflow.id} className="flex items-center gap-3 py-3">
                <Link
                  href={ROUTES.WORKFLOW_DETAIL(workflow.id)}
                  className="hover:text-foreground text-foreground min-w-0 flex-1 truncate text-sm font-medium hover:underline"
                >
                  {workflow.name}
                </Link>
                <Badge variant={STATUS_VARIANT[workflow.status] ?? "secondary"}>
                  {t(`status.${workflow.status}`)}
                </Badge>
                {canCreate ? (
                  <Button
                    variant="ghost"
                    size="icon"
                    disabled={duplicate.isPending}
                    aria-label={t("duplicateWorkflow", { name: workflow.name })}
                    onClick={() => onDuplicate(workflow)}
                  >
                    <Copy className="h-4 w-4" />
                  </Button>
                ) : null}
              </li>
            ))}
          </ul>
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
