"use client";

import { use, useEffect, useMemo, useRef } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  AlertTriangle,
  Bug,
  CircleDollarSign,
  Clock,
  ListChecks,
  RotateCcw,
  Square,
} from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import { PageHeader } from "@/components/dashboard/page-header";
import {
  Alert,
  AlertDescription,
  AlertTitle,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  FigureCard,
  Skeleton,
} from "@/components/ui";
import { JsonView } from "@/components/ui/json-view";
import {
  NodeRunOverlayProvider,
  summarizeNodeRuns,
  WorkflowCanvas,
} from "@/components/workflows/canvas";
import { NodeEditorDialog } from "@/components/workflows/node-editor";
import { RunFiles } from "@/components/workflows/runs/run-files";
import { NodeRunStatusLabel, WorkflowRunStatusBadge } from "@/components/workflows/runs/run-status";
import { useNodeCatalog, usePermissions, useWorkflow, useWorkflowRun } from "@/hooks";
import { ROUTES } from "@/lib/constants";
import { formatDateTime, formatRunDuration } from "@/lib/utils";
import { stepDataOf } from "@/lib/workflows/step-data";
import { isRunRetryable, isRunTerminal, nodeDisplayName, shortNodeId } from "@/lib/workflows/types";
import { Perm } from "@/types/permissions";
import { useWorkflowEditorStore } from "@/stores";

interface PageProps {
  params: Promise<{ id: string; runId: string }>;
}

/**
 * One run: the graph it executed, coloured by what each step did, beside its
 * figures, its error, its output and every step it took.
 *
 * The graph is the run's own - its version's, or a test run's draft snapshot -
 * seeded into the editor store for the read-only canvas the editor uses, so a
 * loop body opens the same way and shows each step's iterations. While the run
 * is live, its state and steps are read again every couple of seconds.
 */
export default function WorkflowRunPage({ params }: PageProps) {
  const { id, runId } = use(params);
  const t = useTranslations("pages.workflows");
  const locale = useLocale();
  const { workflow } = useWorkflow(id);
  const { nodes: catalog } = useNodeCatalog();
  const router = useRouter();
  const { run, isLoading, nodes, files, graph, cancel, retry } = useWorkflowRun(runId);
  const { can } = usePermissions();
  const load = useWorkflowEditorStore((state) => state.load);
  const seedGraph = useWorkflowEditorStore((state) => state.seedGraph);
  const teardown = useWorkflowEditorStore((state) => state.teardown);
  const mergeStepData = useWorkflowEditorStore((state) => state.mergeStepData);
  const seeded = useRef<string | null>(null);

  useEffect(() => {
    if (graph !== null && seeded.current !== runId) {
      seeded.current = runId;
      load({ workflowId: id, expectedRevision: 0 });
      seedGraph(graph);
    }
  }, [graph, runId, id, load, seedGraph]);
  useEffect(
    () => () => {
      teardown();
      seeded.current = null;
    },
    [teardown],
  );
  // What each step handed on in this run, for a step's Input and Output.
  useEffect(() => {
    if (graph !== null) mergeStepData(stepDataOf(runId, nodes));
  }, [graph, runId, nodes, mergeStepData]);

  const summaries = useMemo(() => summarizeNodeRuns(nodes), [nodes]);
  const nameOf = (nodeId: string) => {
    const instance = graph?.nodes.find((node) => node.id === nodeId);
    const definition = catalog.find(
      (entry) =>
        entry.id === instance?.definition_id && entry.version === instance?.definition_version,
    );
    return nodeDisplayName(
      definition?.name ?? instance?.definition_id ?? nodeId,
      nodeId,
      true,
      instance?.label,
    );
  };

  if (isLoading || run === null || !workflow) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-96 w-full" />
      </div>
    );
  }

  const live = !isRunTerminal(run.status);
  // The typed `WorkflowError` the run recorded - its own words, never an exception's.
  const problem = run.error;
  const title = t("runTitle", { id: shortNodeId(run.id) });
  const stepsRun = nodes.filter((node) => node.status === "succeeded").length;

  return (
    <div className="space-y-6">
      <PageHeader
        title={title}
        description={run.mode === "test" ? t("runTestDescription") : t("runRealDescription")}
        breadcrumbs={[
          { label: t("title"), href: ROUTES.WORKFLOWS },
          { label: workflow?.name ?? t("title"), href: ROUTES.WORKFLOW_DETAIL(id) },
          { label: t("runsTitle"), href: ROUTES.WORKFLOW_RUNS(id) },
          { label: title },
        ]}
        badges={<WorkflowRunStatusBadge status={run.status} />}
        actions={
          <>
            {live && can(Perm.workflowsRun) && (
              <Button variant="outline" disabled={cancel.isPending} onClick={() => cancel.mutate()}>
                <Square className="h-4 w-4" />
                {t("cancelRun")}
              </Button>
            )}
            {workflow.can_edit && nodes.some((node) => node.output !== null) && (
              <Button variant="outline" asChild>
                <Link href={`${ROUTES.WORKFLOW_DETAIL(id)}?debug=${runId}`}>
                  <Bug className="h-4 w-4" />
                  {t("runDebug")}
                </Link>
              </Button>
            )}
            {isRunRetryable(run.status) && can(Perm.workflowsRun) && (
              <Button
                disabled={retry.isPending}
                onClick={() =>
                  retry.mutate(undefined, {
                    onSuccess: (started) => router.push(ROUTES.WORKFLOW_RUN_DETAIL(id, started.id)),
                  })
                }
              >
                <RotateCcw className="h-4 w-4" />
                {t("runRetry")}
              </Button>
            )}
          </>
        }
      />

      <div className="grid gap-4 sm:grid-cols-3">
        <FigureCard
          icon={Clock}
          label={t("runDuration")}
          value={formatRunDuration(run.started_at, run.ended_at)}
          caption={run.started_at ? formatDateTime(run.started_at, locale) : undefined}
        />
        <FigureCard
          icon={CircleDollarSign}
          label={t("runCost")}
          value={`$${run.spent_cost.toFixed(4)}${run.cost_is_partial ? "+" : ""}`}
          caption={
            run.budget_limit !== null ? t("runBudget", { limit: run.budget_limit }) : undefined
          }
        />
        <FigureCard
          icon={ListChecks}
          label={t("runSteps")}
          value={String(stepsRun)}
          caption={t("runStepsCaption", { count: nodes.length })}
        />
      </div>

      {run.retry_of_run_id !== null && (
        <p className="text-muted-foreground text-sm">
          {t("runRetryOf")}{" "}
          <Link
            className="text-foreground underline underline-offset-4"
            href={ROUTES.WORKFLOW_RUN_DETAIL(id, run.retry_of_run_id)}
          >
            {t("runTitle", { id: shortNodeId(run.retry_of_run_id) })}
          </Link>
        </p>
      )}

      {problem && (
        <Alert variant="destructive">
          <AlertTriangle className="h-4 w-4" />
          <AlertTitle>{problem.code}</AlertTitle>
          <AlertDescription>{problem.message}</AlertDescription>
        </Alert>
      )}

      <div className="grid gap-4 lg:grid-cols-[1fr_22rem]">
        <div className="border-border bg-card h-[32rem] overflow-hidden rounded-xl border">
          {graph === null ? (
            <Skeleton className="h-full w-full" />
          ) : (
            <NodeRunOverlayProvider value={summaries}>
              <WorkflowCanvas workflow={workflow} catalog={catalog} readOnly />
            </NodeRunOverlayProvider>
          )}
          {graph !== null && (
            <NodeEditorDialog workflowId={id} catalog={catalog} readOnly runData />
          )}
        </div>
        <div className="space-y-4">
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">{t("runOutput")}</CardTitle>
            </CardHeader>
            <CardContent>
              {run.output ? (
                <JsonView value={run.output} />
              ) : (
                <p className="text-muted-foreground text-sm">
                  {live ? t("runOutputPending") : t("runOutputNone")}
                </p>
              )}
            </CardContent>
          </Card>
          <RunFiles runId={run.id} files={files} />
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">{t("runStepList")}</CardTitle>
            </CardHeader>
            <CardContent className="max-h-80 overflow-y-auto">
              <ul className="divide-border divide-y">
                {nodes.map((node) => (
                  <li key={node.id} className="space-y-0.5 py-2">
                    <div className="flex items-center justify-between gap-2">
                      <span className="truncate text-sm">{nameOf(node.node_instance_id)}</span>
                      <NodeRunStatusLabel status={node.status} />
                    </div>
                    <p className="text-muted-foreground text-xs">
                      {node.scope_path.length > 0
                        ? t("runStepIteration", {
                            index: (node.scope_path[node.scope_path.length - 1]?.index ?? 0) + 1,
                          })
                        : t("runStepTopLevel")}
                      {node.attempts > 1 ? ` · ${t("runAttempts", { count: node.attempts })}` : ""}
                    </p>
                    {node.error && <StepProblem problem={node.error} />}
                  </li>
                ))}
              </ul>
            </CardContent>
          </Card>
        </div>
      </div>
    </div>
  );
}

/** A step's recorded `WorkflowError`, as its code and its own sentence. */
function StepProblem({ problem }: { problem: { code: string; message: string } }) {
  return (
    <p className="text-destructive text-xs">
      {problem.code}: {problem.message}
    </p>
  );
}
