"use client";

import { use, useEffect, useMemo, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  AlertTriangle,
  Bug,
  CircleDollarSign,
  Clock,
  ListChecks,
  RotateCcw,
  ScrollText,
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
import {
  NodeRunOverlayProvider,
  summarizeNodeRuns,
  WorkflowCanvas,
} from "@/components/workflows/canvas";
import { NodeEditorDialog } from "@/components/workflows/node-editor";
import { RunAnswer } from "@/components/workflows/runs/run-answer";
import { outcomeLabels } from "@/components/workflows/logs/outcome-labels";
import { StepLogs } from "@/components/workflows/logs/step-logs";
import { RunFiles } from "@/components/workflows/runs/run-files";
import { StepAttentionDialog } from "@/components/workflows/runs/step-attention-dialog";
import { NodeRunStatusLabel, WorkflowRunStatusBadge } from "@/components/workflows/runs/run-status";
import {
  useCausingRun,
  useNodeCatalog,
  usePermissions,
  useWorkflow,
  useWorkflowRun,
} from "@/hooks";
import { ROUTES } from "@/lib/constants";
import { formatRunCostUsd, formatDateTime, formatRunDuration } from "@/lib/utils";
import { routesErrors } from "@/lib/workflows/ports";
import { stepDataOf } from "@/lib/workflows/step-data";
import {
  isRunRetryable,
  isRunTerminal,
  type NodeInstance,
  nodeDisplayName,
  type WorkflowNodeRunRead,
  shortNodeId,
} from "@/lib/workflows/types";
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
  const { nodes: catalog, isLoading: catalogLoading } = useNodeCatalog();
  const router = useRouter();
  const { run, isLoading, nodes, files, logs, logsError, graph, cancel, retry, resolveStep } =
    useWorkflowRun(runId);
  const [resolving, setResolving] = useState<string | null>(null);
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
  const live = run !== null && !isRunTerminal(run.status);
  // Watched while it went: its failure shakes and its wires move. A run opened
  // once it had ended is drawn still.
  const [watched, setWatched] = useState(false);
  if (live && !watched) setWatched(true);
  const overlay = useMemo(() => ({ summaries, live, watched }), [summaries, live, watched]);
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

  const labelsOf = (nodeId: string) => {
    const instance = graph?.nodes.find((node) => node.id === nodeId);
    return instance === undefined
      ? new Map<string, string>()
      : outcomeLabels(
          instance,
          catalog.find(
            (entry) =>
              entry.id === instance.definition_id && entry.version === instance.definition_version,
          ),
        );
  };

  // As the editor does, the canvas waits for the catalog its cards are drawn from.
  if (isLoading || catalogLoading || run === null || !workflow) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-96 w-full" />
      </div>
    );
  }

  // The typed `WorkflowError` the run recorded - its own words, never an exception's.
  const problem = run.error;
  const title = t("runTitle", { id: shortNodeId(run.id) });
  const stepsRun = nodes.filter((node) => node.status === "succeeded").length;
  const resolvingNode = nodes.find((node) => node.id === resolving) ?? null;
  const resolvingInstance = graph?.nodes.find(
    (entry) => entry.id === resolvingNode?.node_instance_id,
  );
  // A step that finished after the run had already stopped: its work happened.
  const finishedLate = (node: WorkflowNodeRunRead) =>
    node.status === "succeeded" &&
    run.ended_at !== null &&
    node.ended_at !== null &&
    Date.parse(node.ended_at) > Date.parse(run.ended_at);

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
            {live && run.can_cancel && (
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
            <Button variant="outline" asChild>
              {/* A test run's lines stay out of the log unless it is asked for them. */}
              <Link
                href={`${ROUTES.WORKFLOW_LOGS(id)}?run=${run.id}${run.mode === "test" ? "&test=1" : ""}`}
              >
                <ScrollText className="h-4 w-4" />
                {t("runSeeInLogs")}
              </Link>
            </Button>
            {isRunRetryable(run.status) &&
              can(Perm.workflowsRun) &&
              (run.mode === "real" || workflow.can_edit) && (
                <Button
                  disabled={retry.isPending}
                  onClick={() =>
                    retry.mutate(undefined, {
                      onSuccess: (started) =>
                        router.push(ROUTES.WORKFLOW_RUN_DETAIL(id, started.id)),
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
          value={formatRunCostUsd(run.spent_cost, run.cost_is_partial)}
          caption={
            run.budget_limit !== null ? t("runBudget", { limit: run.budget_limit }) : undefined
          }
        />
        <FigureCard
          icon={ListChecks}
          label={t("runSteps")}
          value={t("runStepsOf", { done: stepsRun, count: nodes.length })}
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

      {run.causation_run_id !== null && (
        <CausedBy runId={run.causation_run_id} triggeredBy={run.triggered_by} />
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
            <NodeRunOverlayProvider value={overlay}>
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
                <RunAnswer output={run.output} />
              ) : (
                <p className="text-muted-foreground text-sm">
                  {live ? t("runOutputPending") : t("runOutputNone")}
                </p>
              )}
            </CardContent>
          </Card>
          <Card>
            <CardHeader className="pb-2">
              <CardTitle className="text-sm">{t("runStepList")}</CardTitle>
            </CardHeader>
            <CardContent className="max-h-80 overflow-y-auto">
              {logsError !== null && (
                <p role="alert" className="text-destructive pb-2 text-xs">
                  {t("runLogsFailed")}
                </p>
              )}
              <ul className="divide-border divide-y">
                {nodes.map((node, index) => (
                  <li key={node.id} className="space-y-0.5 py-2">
                    <div className="flex items-center justify-between gap-2">
                      <span className="truncate text-sm">{nameOf(node.node_instance_id)}</span>
                      <NodeRunStatusLabel status={node.status} />
                    </div>
                    {(finishedLate(node) ||
                      (live && node.status === "needs_attention" && run.can_cancel)) && (
                      <div className="flex items-center justify-between gap-2">
                        {finishedLate(node) && (
                          <p className="text-muted-foreground text-xs">
                            {t("runStepFinishedLate")}
                          </p>
                        )}
                        {live && node.status === "needs_attention" && run.can_cancel && (
                          <Button size="sm" variant="outline" onClick={() => setResolving(node.id)}>
                            {t("runStepResolve")}
                          </Button>
                        )}
                      </div>
                    )}
                    <p className="text-muted-foreground text-xs">
                      {node.scope_path.length > 0
                        ? t("runStepIteration", {
                            index: (node.scope_path[node.scope_path.length - 1]?.index ?? 0) + 1,
                          })
                        : t("runStepTopLevel")}
                      {node.attempts > 1 ? ` · ${t("runAttempts", { count: node.attempts })}` : ""}
                    </p>
                    {node.error && <StepProblem problem={node.error} />}
                    <CalledRun
                      config={graph?.nodes.find((entry) => entry.id === node.node_instance_id)}
                      output={node.output}
                    />
                    {/* A step's lines are one list, under its first row - a loop's
                        iterations are rows of the same step. */}
                    {nodes.findIndex(
                      (entry) => entry.node_instance_id === node.node_instance_id,
                    ) === index && (
                      <StepLogs
                        entries={logs.filter(
                          (entry) => entry.node_instance_id === node.node_instance_id,
                        )}
                        labels={labelsOf(node.node_instance_id)}
                      />
                    )}
                  </li>
                ))}
              </ul>
            </CardContent>
          </Card>
          <RunFiles runId={run.id} files={files} />
        </div>
      </div>

      {resolvingNode?.status === "needs_attention" && resolvingInstance !== undefined && (
        <StepAttentionDialog
          node={resolvingNode}
          stepName={nameOf(resolvingNode.node_instance_id)}
          definition={catalog.find(
            (entry) =>
              entry.id === resolvingInstance.definition_id &&
              entry.version === resolvingInstance.definition_version,
          )}
          routesErrors={routesErrors(resolvingInstance)}
          inLoop={resolvingNode.scope_path.length > 0}
          open
          busy={resolveStep.isPending}
          onOpenChange={(open) => {
            if (!open) setResolving(null);
          }}
          onResolve={(choice) =>
            resolveStep.mutate(
              { nodeRunId: resolvingNode.id, choice },
              { onSuccess: () => setResolving(null) },
            )
          }
        />
      )}
    </div>
  );
}

/** What started this run, linked where the viewer may open it. */
function CausedBy({ runId, triggeredBy }: { runId: string; triggeredBy: string }) {
  const t = useTranslations("pages.workflows");
  const { causing, refused } = useCausingRun(runId);
  const cause =
    triggeredBy === "workflow_call" || triggeredBy === "workflow_failed" ? triggeredBy : "other";
  return (
    <p className="text-muted-foreground text-sm">
      {t(`runCausedBy.${cause}`)}{" "}
      {causing !== null ? (
        <Link
          className="text-foreground underline underline-offset-4"
          href={ROUTES.WORKFLOW_RUN_DETAIL(causing.workflow_id, causing.id)}
        >
          {t("runTitle", { id: shortNodeId(causing.id) })}
        </Link>
      ) : (
        refused && t("runCausedByHidden")
      )}
    </p>
  );
}

/** A Run a workflow step's link to the run it started, once it has one. */
function CalledRun({
  config,
  output,
}: {
  config: NodeInstance | undefined;
  output: Record<string, unknown> | null;
}) {
  const t = useTranslations("pages.workflows");
  const workflowId = config?.config["workflow_id"];
  const called = output?.["run_id"];
  if (
    config?.definition_id !== "workflow.run" ||
    typeof workflowId !== "string" ||
    typeof called !== "string"
  ) {
    return null;
  }
  return (
    <Link
      className="text-xs underline underline-offset-4"
      href={ROUTES.WORKFLOW_RUN_DETAIL(workflowId, called)}
    >
      {t("runOpenCalled", { id: shortNodeId(called) })}
    </Link>
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
