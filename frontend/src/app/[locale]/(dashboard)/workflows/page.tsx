"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { Plus, Workflow } from "lucide-react";
import { useTranslations } from "next-intl";

import { PageHeader } from "@/components/dashboard/page-header";
import { Button, ListCard, ListCardEmpty } from "@/components/ui";
import { usePermissions, useWorkflows } from "@/hooks";
import { ROUTES } from "@/lib/constants";
import { Perm } from "@/types/permissions";

/**
 * The workflows list — draft / published / archived, like the agents list.
 *
 * Foundation shell: it lists what the caller can see and offers a permission-
 * gated create. Duplicate, templates and the status filter are the list leaf's.
 */
export default function WorkflowsPage() {
  const t = useTranslations("pages.workflows");
  const router = useRouter();
  const { workflows, isLoading, create } = useWorkflows();
  const { can } = usePermissions();
  const canCreate = can(Perm.workflowsCreate);

  const onCreate = () =>
    create.mutate(
      { name: t("untitledWorkflow") },
      { onSuccess: (workflow) => router.push(ROUTES.WORKFLOW_DETAIL(workflow.id)) },
    );

  return (
    <div className="space-y-6">
      <PageHeader
        title={t("title")}
        description={t("description")}
        actions={
          canCreate ? (
            <Button onClick={onCreate} disabled={create.isPending} data-tour="workflows-new">
              <Plus className="h-4 w-4" />
              {t("newWorkflow")}
            </Button>
          ) : undefined
        }
      />

      <ListCard
        title={t("catalog")}
        counted={isLoading ? null : t("shownCount", { count: workflows.length })}
      >
        {workflows.length === 0 ? (
          <ListCardEmpty
            icon={Workflow}
            title={t("noWorkflowsYet")}
            description={canCreate ? t("createFirst") : t("nobodyHasShared")}
          />
        ) : (
          <ul className="divide-border divide-y">
            {workflows.map((workflow) => (
              <li key={workflow.id}>
                <Link
                  href={ROUTES.WORKFLOW_DETAIL(workflow.id)}
                  className="hover:text-foreground text-foreground block py-3 text-sm font-medium hover:underline"
                >
                  {workflow.name}
                </Link>
              </li>
            ))}
          </ul>
        )}
      </ListCard>
    </div>
  );
}
