"use client";

import { use, useEffect } from "react";
import { Workflow } from "lucide-react";
import { useTranslations } from "next-intl";

import { PageHeader } from "@/components/dashboard/page-header";
import { WorkflowCanvas } from "@/components/workflows/canvas";
import { NodePalette } from "@/components/workflows/palette";
import { PropertyPanel } from "@/components/workflows/property-panel";
import { ListCard, ListCardEmpty, Skeleton } from "@/components/ui";
import { useNodeCatalog, useWorkflow } from "@/hooks";
import { ROUTES } from "@/lib/constants";
import { useWorkflowEditorStore } from "@/stores";

interface PageProps {
  params: Promise<{ id: string }>;
}

/**
 * The workflow editor shell — palette, canvas and property panel.
 *
 * It loads the workflow (`WorkflowDetail`, carrying `draft_graph`/`draft_revision`)
 * and the node catalog into TanStack Query and hands the coordination facts
 * (`workflowId`, `draft_revision`) to the editor store; the graph itself stays in
 * Query and the canvas leaf's own state, never the store. The editor tree is
 * keyed on the workflow id so a switch remounts it, and the store bumps its
 * generation on every `load`. Each region is a placeholder its leaf fills.
 */
export default function WorkflowEditorPage({ params }: PageProps) {
  const { id } = use(params);
  const t = useTranslations("pages.workflows");
  const { workflow, isLoading } = useWorkflow(id);
  const { nodes } = useNodeCatalog();
  const load = useWorkflowEditorStore((state) => state.load);
  const teardown = useWorkflowEditorStore((state) => state.teardown);

  useEffect(() => {
    if (workflow) load({ workflowId: workflow.id, expectedRevision: workflow.draft_revision });
  }, [workflow, load]);

  // The store is torn down (not merely reset) on unmount, so no cross-workflow
  // or cross-organization state survives leaving the editor.
  useEffect(() => () => teardown(), [teardown]);

  if (isLoading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-96 w-full" />
      </div>
    );
  }

  if (!workflow) {
    return (
      <div className="space-y-6">
        <PageHeader
          title={t("notFound")}
          breadcrumbs={[{ label: t("title"), href: ROUTES.WORKFLOWS }, { label: t("notFound") }]}
        />
        <ListCard title={t("notFound")} counted={null}>
          <ListCardEmpty icon={Workflow} title={t("notFound")} description={t("notFoundDetail")} />
        </ListCard>
      </div>
    );
  }

  return (
    <div key={workflow.id} className="space-y-6">
      <PageHeader
        title={workflow.name}
        description={t("draftRevision", { revision: workflow.draft_revision })}
        breadcrumbs={[{ label: t("title"), href: ROUTES.WORKFLOWS }, { label: workflow.name }]}
      />
      <div className="grid gap-4 lg:grid-cols-[16rem_1fr_20rem]">
        <NodePalette nodes={nodes} />
        <WorkflowCanvas workflow={workflow} />
        <PropertyPanel />
      </div>
    </div>
  );
}
