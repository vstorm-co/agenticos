"use client";

import { use, useEffect, useRef } from "react";
import { Workflow } from "lucide-react";
import { useTranslations } from "next-intl";

import { PageHeader } from "@/components/dashboard/page-header";
import { WorkflowCanvas } from "@/components/workflows/canvas";
import { ConflictBanner, EditorActions, VersionHistory } from "@/components/workflows/editor";
import { NodePalette } from "@/components/workflows/palette";
import { PropertyPanel } from "@/components/workflows/property-panel";
import { ListCard, ListCardEmpty, Skeleton } from "@/components/ui";
import { useNodeCatalog, useWorkflow } from "@/hooks";
import { ROUTES } from "@/lib/constants";
import type { WorkflowGraph } from "@/lib/workflows/types";
import { useWorkflowEditorStore } from "@/stores";

interface PageProps {
  params: Promise<{ id: string }>;
}

/** The graph a workflow nobody has edited starts from, since its `draft_graph` is null. */
const EMPTY_GRAPH: WorkflowGraph = {
  entry_node_id: "",
  nodes: [],
  edges: [],
  bindings: [],
  scopes: [],
};

/**
 * The workflow editor shell — palette, canvas, property panel, publish control,
 * conflict banner and version history.
 *
 * It loads the workflow (`WorkflowDetail`, carrying `draft_graph`/`draft_revision`)
 * and the node catalog into TanStack Query and hands the coordination facts
 * (`workflowId`, `draft_revision`) to the editor store; the graph itself lives in
 * the store, seeded once per workflow. The editor tree is keyed on the workflow id
 * so a switch remounts it, and the store bumps its generation on every `load`.
 *
 * The seed is deliberately once-per-id: autosave's own success invalidates the
 * detail query, and reseeding the store from that background refetch would throw
 * away edits made while the save was in flight. The store's revision is advanced
 * by autosave, not by the refetch.
 */
export default function WorkflowEditorPage({ params }: PageProps) {
  const { id } = use(params);
  const t = useTranslations("pages.workflows");
  const { workflow, isLoading, saveDraft, publish } = useWorkflow(id);
  const { nodes } = useNodeCatalog();
  const load = useWorkflowEditorStore((state) => state.load);
  const seedGraph = useWorkflowEditorStore((state) => state.seedGraph);
  const teardown = useWorkflowEditorStore((state) => state.teardown);
  const seededId = useRef<string | null>(null);

  useEffect(() => {
    if (workflow && seededId.current !== workflow.id) {
      seededId.current = workflow.id;
      load({ workflowId: workflow.id, expectedRevision: workflow.draft_revision });
      seedGraph(workflow.draft_graph ?? EMPTY_GRAPH);
    }
  }, [workflow, load, seedGraph]);

  // The store is torn down (not merely reset) on unmount, so no cross-workflow
  // or cross-organization state survives leaving the editor.
  useEffect(
    () => () => {
      teardown();
      seededId.current = null;
    },
    [teardown],
  );

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
        actions={
          <EditorActions
            catalog={nodes}
            saveDraft={saveDraft.mutateAsync}
            publish={publish.mutateAsync}
          />
        }
      />
      <ConflictBanner workflowId={workflow.id} />
      <div className="grid gap-4 lg:grid-cols-[16rem_1fr_20rem]">
        <NodePalette nodes={nodes} />
        <WorkflowCanvas workflow={workflow} catalog={nodes} />
        <PropertyPanel />
      </div>
      <VersionHistory workflowId={workflow.id} catalog={nodes} />
    </div>
  );
}
