"use client";

import { use, useState } from "react";
import { useRouter } from "next/navigation";
import { Play } from "lucide-react";
import { useTranslations } from "next-intl";

import { PageHeader } from "@/components/dashboard/page-header";
import { Button } from "@/components/ui";
import { RunHistory } from "@/components/workflows/runs/run-history";
import { StartRunDialog } from "@/components/workflows/runs/start-run-dialog";
import { usePermissions, useWorkflow, useWorkflowRuns, useWorkflowVersion } from "@/hooks";
import { ROUTES } from "@/lib/constants";
import { declaredFields, sampleRunInput, startsByHand } from "@/lib/workflows/triggers";
import { Perm } from "@/types/permissions";

interface PageProps {
  params: Promise<{ id: string }>;
}

/**
 * A workflow's runs, newest first and filtered on the server, and starting one
 * by hand.
 *
 * The list polls while any run on it is still moving, so a run started here
 * walks through its statuses without a reload. A row opens the run.
 */
export default function WorkflowRunsPage({ params }: PageProps) {
  const { id } = use(params);
  const t = useTranslations("pages.workflows");
  const router = useRouter();
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
    startsByHand(workflow.live_trigger);

  return (
    <div className="space-y-6">
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
      {startOpen && (
        <StartRunDialog
          open
          onOpenChange={setStartOpen}
          canRunLive={canRunLive}
          canTest={canTest}
          busy={start.isPending}
          sampleInput={sampleRunInput(workflow?.draft_graph ?? null)}
          testFields={declaredFields(workflow?.draft_graph)}
          liveFields={declaredFields(live?.graph)}
          onStart={({ mode, input }) =>
            start.mutate(
              { workflow_id: id, mode, input },
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
