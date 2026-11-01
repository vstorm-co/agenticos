"use client";

import { use, useState } from "react";
import { useRouter } from "next/navigation";
import { Play } from "lucide-react";
import { useTranslations } from "next-intl";

import { PageHeader } from "@/components/dashboard/page-header";
import { Button, MoreOptions } from "@/components/ui";
import { RunHistory } from "@/components/workflows/runs/run-history";
import { StartRunDialog } from "@/components/workflows/runs/start-run-dialog";
import { WorkflowStats } from "@/components/workflows/runs/workflow-stats";
import { usePermissions, useWorkflow, useWorkflowRuns, useWorkflowVersion } from "@/hooks";
import { ROUTES } from "@/lib/constants";
import {
  declaredFields,
  sampleRunInput,
  startsByHand,
  entryNodes,
  entryGraph,
} from "@/lib/workflows/triggers";
import type { WorkflowGraph } from "@/lib/workflows/types";
import { Perm } from "@/types/permissions";

interface PageProps {
  params: Promise<{ id: string }>;
}

/**
 * A workflow's runs: what they did over a window, the runs themselves newest
 * first and filtered on the server, and starting one by hand.
 *
 * The list polls while any run on it is still moving, so a run started here
 * walks through its statuses without a reload. A row opens the run.
 */
export default function WorkflowRunsPage({ params }: PageProps) {
  const { id } = use(params);
  const t = useTranslations("pages.workflows");
  const router = useRouter();
  const ts = useTranslations("pages.workflows.stats");
  const { workflow } = useWorkflow(id);
  const { start } = useWorkflowRuns(id);
  const { can } = usePermissions();
  const [startOpen, setStartOpen] = useState(false);
  // The live version's graph, only once the dialog is open: its trigger's fields
  // are what a real run is asked for.
  const { version: live } = useWorkflowVersion(
    id,
    startOpen ? (workflow?.current_version_id ?? null) : null,
  );
  const canTest = can(Perm.workflowsEdit) && workflow?.status !== "archived";
  // Only a version that starts by hand is started from here: every other
  // trigger has its own surface, and the server refuses this door for it.
  const canRunLive =
    can(Perm.workflowsRun) &&
    workflow?.current_version_id != null &&
    (workflow.live_triggers?.length
      ? workflow.live_triggers.some((trigger) => startsByHand(trigger))
      : startsByHand(workflow.live_trigger));

  const choices = (graph: WorkflowGraph | null | undefined, byHand = false) =>
    graph === null || graph === undefined
      ? []
      : entryNodes(graph)
          .filter((node) => !byHand || startsByHand(node.definition_id))
          .map((node) => {
            const branch = entryGraph(graph, node.id);
            return {
              id: node.id,
              name: node.label ?? node.definition_id,
              fields: declaredFields(branch),
              sample: sampleRunInput(branch),
            };
          });
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-6">
      <PageHeader
        title={t("runsTitle")}
        description={t("runsDescription")}
        breadcrumbs={[
          { label: t("title"), href: ROUTES.WORKFLOWS },
          { label: workflow?.name ?? t("runsTitle"), href: ROUTES.WORKFLOW_DETAIL(id) },
          { label: t("runsTitle") },
        ]}
        actions={
          canTest || canRunLive ? (
            <Button onClick={() => setStartOpen(true)}>
              <Play className="h-4 w-4" />
              {t("startRun")}
            </Button>
          ) : undefined
        }
      />
      <RunHistory workflowId={id} />
      <div className="bg-card rounded-xl border p-4">
        <MoreOptions label={ts("heading")}>
          <WorkflowStats workflowId={id} />
        </MoreOptions>
      </div>
      {startOpen && (
        <StartRunDialog
          open
          onOpenChange={setStartOpen}
          canRunLive={canRunLive}
          canTest={canTest}
          busy={start.isPending}
          sampleInput={sampleRunInput(workflow?.draft_graph ?? null)}
          entries={choices(workflow?.draft_graph)}
          liveEntries={choices(live?.graph, true)}
          testFields={declaredFields(workflow?.draft_graph)}
          liveFields={declaredFields(live?.graph)}
          onStart={({ mode, input, entry_node_id }) =>
            start.mutate(
              { workflow_id: id, mode, input, ...(entry_node_id ? { entry_node_id } : {}) },
              {
                onSuccess: (run) => {
                  setStartOpen(false);
                  router.push(ROUTES.WORKFLOW_RUN_DETAIL(id, run.id));
                },
              },
            )
          }
        />
      )}
    </div>
  );
}
