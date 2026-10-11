"use client";

import { useMemo, useState } from "react";
import { FlaskConical, Pencil, Pin, PinOff, Unplug } from "lucide-react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { Badge, Button, ConfirmDialog, Spinner, Textarea } from "@/components/ui";
import { nodeVisual } from "@/components/workflows/node-visuals";
import { StartRunDialog } from "@/components/workflows/runs/start-run-dialog";
import { validateGraph } from "@/components/workflows/validation";
import { useWorkflowRuns, useWorkflowTable } from "@/hooks";
import {
  MAX_PINNED_BYTES,
  isInsideALoop,
  jsonBytes,
  knownInput,
  knownOutputs,
  sourcesOf,
} from "@/lib/workflows/step-data";
import { effectiveDefinition } from "@/lib/workflows/ports";
import { WEBHOOK_TRIGGER, declaredFields, sampleRunInput } from "@/lib/workflows/triggers";
import type { NodeDefinition, NodeInstance, WorkflowGraph } from "@/lib/workflows/types";
import { cn } from "@/lib/utils";
import { useWorkflowEditorStore } from "@/stores/workflow-editor-store";

import { DataView, DeclaredOutput } from "./data-view";
import { WebhookListener } from "./webhook-listener";

function Pane({
  title,
  actions,
  children,
}: {
  title: string;
  actions?: React.ReactNode;
  children: React.ReactNode;
}) {
  return (
    <section aria-label={title} className="flex min-h-0 flex-col">
      <div className="flex min-h-8 items-center justify-between gap-2 pb-2">
        <h3 className="text-muted-foreground text-xs font-medium tracking-wide uppercase">
          {title}
        </h3>
        {actions}
      </div>
      <div className="min-h-0 flex-1 space-y-3 overflow-y-auto">{children}</div>
    </section>
  );
}

function Empty({ children }: { children: React.ReactNode }) {
  return (
    <p className="border-border text-muted-foreground rounded-lg border border-dashed px-3 py-6 text-center text-xs">
      {children}
    </p>
  );
}

/**
 * What a step reads: the data each step it is bound to, or wired from, handed
 * on the last time a test run reached it.
 */
export function InputPane({
  graph,
  catalog,
  node,
  names,
  readOnly = false,
}: {
  graph: WorkflowGraph;
  /** Where a step with no data yet finds the fields it declares. */
  catalog: NodeDefinition[];
  node: NodeInstance;
  names: Map<string, string>;
  /** A run's view: what that run's steps handed on, whatever is pinned on them. */
  readOnly?: boolean;
}) {
  const t = useTranslations("workflows");
  const stepData = useWorkflowEditorStore((state) => state.stepData);
  const sources = sourcesOf(graph, node.id);
  /** The step's catalog entry, with the ports this instance has. */
  const declared = (source: string) => {
    const instance = graph.nodes.find((candidate) => candidate.id === source);
    const definition = catalog.find(
      (entry) =>
        entry.id === instance?.definition_id && entry.version === instance.definition_version,
    );
    return instance && definition ? effectiveDefinition(instance, definition) : null;
  };

  const known = sources.some(
    (source) =>
      stepData[source]?.output != null ||
      (declared(source)?.ports ?? []).some((port) => port.kind === "output"),
  );

  return (
    <Pane title={t("stepInput")}>
      {sources.length === 0 && (
        <div className="border-border flex flex-col items-center gap-2 rounded-lg border border-dashed px-4 py-8 text-center">
          <Unplug aria-hidden="true" className="text-muted-foreground size-5" />
          <p className="text-sm font-medium">{t("stepInputUnconnected")}</p>
          <p className="text-muted-foreground text-xs">{t("stepInputUnconnectedHint")}</p>
        </div>
      )}
      {/* A run's view has no parameters to drag onto. */}
      {!readOnly && known && <p className="text-muted-foreground text-xs">{t("dataDragHint")}</p>}
      {sources.map((source) => {
        const pinned = readOnly
          ? null
          : graph.nodes.find((candidate) => candidate.id === source)?.pinned_output;
        const output = pinned ?? stepData[source]?.output ?? null;
        const definition = declared(source);
        const instance = graph.nodes.find((candidate) => candidate.id === source);
        const visual = nodeVisual(instance?.definition_id ?? "", definition?.category ?? "");
        const Icon = visual.icon;
        return (
          <div key={source} className="space-y-2">
            <div className="flex items-center gap-2 text-sm font-medium">
              <span
                className={cn(
                  "flex size-6 shrink-0 items-center justify-center rounded-md",
                  visual.tileClass,
                )}
              >
                <Icon aria-hidden="true" className="size-3.5" />
              </span>
              <span className="truncate">{names.get(source) ?? source}</span>
              {pinned != null && <Badge variant="outline">{t("stepPinned")}</Badge>}
            </div>
            {output === null ? (
              <DeclaredOutput
                definition={definition}
                source={source}
                intro={t("dataDeclared")}
                fallback={<Empty>{t("stepNoDataYet")}</Empty>}
              />
            ) : (
              <StepDataView node={instance} value={output} source={source} />
            )}
          </div>
        );
      })}
    </Pane>
  );
}

/** The table a step reads or writes, from its `table` setting. */
function tableIdOf(node: NodeInstance | undefined): string | null {
  const ref = node?.config.table;
  return typeof ref === "object" &&
    ref !== null &&
    "table_id" in ref &&
    typeof ref.table_id === "string"
    ? ref.table_id
    : null;
}

/** A step's data, a table step's in its table's column order. */
function StepDataView({
  node,
  value,
  source,
}: {
  node: NodeInstance | undefined;
  value: Record<string, unknown>;
  source?: string;
}) {
  const { table } = useWorkflowTable(tableIdOf(node));
  const order = useMemo(
    () => table?.columns.flatMap((column) => [column.label, column.id]) ?? [],
    [table],
  );
  return <DataView value={value} source={source} order={order} />;
}

/**
 * What a step hands on: its pinned data, or what it handed on the last time a
 * test run reached it - with **Test step** to run it alone on what the steps
 * before it are known to hand on, and pinning, so a test run uses the data
 * instead of calling the step again.
 */
export function OutputPane({
  workflowId,
  catalog,
  graph,
  node,
  definition,
  readOnly = false,
}: {
  /** A run's view: what the step handed on in that run, with nothing to test or pin. */
  readOnly?: boolean;
  workflowId: string;
  catalog: NodeDefinition[];
  graph: WorkflowGraph;
  node: NodeInstance;
  definition: NodeDefinition;
}) {
  const t = useTranslations("workflows");
  const tp = useTranslations("pages.workflows");
  const stepData = useWorkflowEditorStore((state) => state.stepData);
  const isDirty = useWorkflowEditorStore((state) => state.isDirty);
  const testingNodeId = useWorkflowEditorStore((state) => state.testingNodeId);
  const watchRun = useWorkflowEditorStore((state) => state.watchRun);
  const updateNodeDetails = useWorkflowEditorStore((state) => state.updateNodeDetails);
  const { start } = useWorkflowRuns(workflowId);
  const [confirming, setConfirming] = useState(false);
  const [asking, setAsking] = useState(false);
  const [draft, setDraft] = useState<string | null>(null);
  const [draftProblem, setDraftProblem] = useState<string | null>(null);

  const problems = useMemo(
    () => validateGraph(graph, { items: catalog, total: catalog.length }, t),
    [graph, catalog, t],
  );
  const data = stepData[node.id];
  const pinned = readOnly ? null : (node.pinned_output ?? null);
  const testing = testingNodeId === node.id || start.isPending;
  const canPin = !readOnly && definition.kind !== "control";
  const blocked = isInsideALoop(graph, node.id)
    ? t("stepTestInsideALoop")
    : problems.length > 0
      ? tp("runBlockedByProblems", { count: problems.length })
      : isDirty
        ? t("publishSaving")
        : null;

  const test = (input: Record<string, unknown>) =>
    start.mutate(
      {
        workflow_id: workflowId,
        mode: "test",
        input,
        step: { node_id: node.id, outputs: knownOutputs(graph, node.id, stepData) },
      },
      {
        onSuccess: (run) => {
          setAsking(false);
          watchRun(run.id, node.id);
        },
      },
    );
  const begin = () => {
    const input = knownInput(graph, stepData);
    if (input !== null) test(input);
    else if (declaredFields(graph).length > 0) setAsking(true);
    else test(sampleRunInput(graph));
  };
  const ask = () => (definition.effect_kind === "write" ? setConfirming(true) : begin());

  const save = () => {
    let parsed: unknown;
    try {
      parsed = JSON.parse(draft as string);
    } catch {
      setDraftProblem(t("stepPinNotJson"));
      return;
    }
    if (typeof parsed !== "object" || parsed === null || Array.isArray(parsed)) {
      setDraftProblem(t("stepPinNotObject"));
      return;
    }
    if (jsonBytes(parsed) > MAX_PINNED_BYTES) {
      setDraftProblem(t("stepPinTooLarge", { limit: MAX_PINNED_BYTES }));
      return;
    }
    updateNodeDetails(node.id, { pinned_output: parsed as Record<string, unknown> });
    setDraft(null);
  };
  const edit = (value: Record<string, unknown> | null) => {
    setDraftProblem(null);
    setDraft(JSON.stringify(value ?? {}, null, 2));
  };

  const shown = pinned ?? data?.output ?? null;
  // How the step failed in the last run: a node's own failure, not a refusal.
  const failed = data?.error;
  return (
    <Pane
      title={t("stepOutput")}
      actions={
        readOnly ? undefined : (
          <Button
            size="sm"
            // The one thing to do while nothing has been seen yet.
            variant={shown === null && failed == null ? "default" : "outline"}
            disabled={blocked !== null || testing}
            title={blocked ?? t("stepTestHint")}
            onClick={ask}
          >
            {testing ? <Spinner className="size-3.5" /> : <FlaskConical className="size-3.5" />}
            {t("stepTest")}
          </Button>
        )
      }
    >
      {draft !== null ? (
        <div className="space-y-2">
          <Textarea
            aria-label={t("stepPinEditor")}
            value={draft}
            onChange={(event) => setDraft(event.target.value)}
            className="min-h-60 font-mono text-xs"
          />
          {draftProblem !== null && <p className="text-destructive text-xs">{draftProblem}</p>}
          <div className="flex justify-end gap-2">
            <Button size="sm" variant="ghost" onClick={() => setDraft(null)}>
              {t("stepPinCancel")}
            </Button>
            <Button size="sm" onClick={save}>
              {t("stepPinSave")}
            </Button>
          </div>
        </div>
      ) : (
        <>
          {!readOnly && definition.id === WEBHOOK_TRIGGER && (
            <WebhookListener
              workflowId={workflowId}
              onCaught={(delivery) => {
                updateNodeDetails(node.id, { pinned_output: delivery });
                toast.success(t("webhookTestCaught"));
              }}
            />
          )}
          {pinned !== null && (
            <p className="bg-muted text-muted-foreground rounded-md px-2.5 py-1.5 text-xs">
              {t("stepPinnedHint")}
            </p>
          )}
          {pinned === null && failed != null && (
            <div className="border-destructive/30 bg-destructive/5 text-destructive rounded-md border px-2.5 py-1.5 text-xs">
              {failed.code}: {failed.message}
            </div>
          )}
          {shown === null ? (
            failed == null && (
              <DeclaredOutput
                definition={effectiveDefinition(node, definition)}
                intro={t("stepOutputDeclared")}
                fallback={<Empty>{t("stepOutputNone")}</Empty>}
              />
            )
          ) : (
            <StepDataView node={node} value={shown} />
          )}
          {canPin && (
            <div className="flex flex-wrap gap-2">
              {pinned !== null ? (
                <>
                  <Button size="sm" variant="ghost" onClick={() => edit(pinned)}>
                    <Pencil className="size-3.5" />
                    {t("stepPinEdit")}
                  </Button>
                  <Button
                    size="sm"
                    variant="ghost"
                    onClick={() => updateNodeDetails(node.id, { pinned_output: null })}
                  >
                    <PinOff className="size-3.5" />
                    {t("stepUnpin")}
                  </Button>
                </>
              ) : (
                <>
                  {data?.output != null && (
                    <Button
                      size="sm"
                      variant="ghost"
                      onClick={() => updateNodeDetails(node.id, { pinned_output: data.output })}
                    >
                      <Pin className="size-3.5" />
                      {t("stepPin")}
                    </Button>
                  )}
                  <Button size="sm" variant="ghost" onClick={() => edit(data?.output ?? null)}>
                    <Pencil className="size-3.5" />
                    {t("stepPinWrite")}
                  </Button>
                </>
              )}
            </div>
          )}
        </>
      )}
      <ConfirmDialog
        open={confirming}
        onOpenChange={setConfirming}
        title={t("stepTestWriteTitle")}
        description={t("stepTestWriteDescription")}
        confirmLabel={t("stepTest")}
        onConfirm={() => {
          setConfirming(false);
          begin();
        }}
      />
      {asking && (
        <StartRunDialog
          open
          onOpenChange={setAsking}
          canRunLive={false}
          canTest
          busy={start.isPending}
          testFields={declaredFields(graph)}
          onStart={({ input }) => test(input)}
        />
      )}
    </Pane>
  );
}
