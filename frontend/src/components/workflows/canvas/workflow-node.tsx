"use client";

import { Handle, type NodeProps, Position } from "@xyflow/react";
import { CanvasNoteCard } from "./canvas-note";
import {
  AlertTriangle,
  ArrowUpRight,
  Cable,
  CirclePause,
  Pin,
  RotateCw,
  ShieldAlert,
  StickyNote,
  Timer,
} from "lucide-react";
import { useTranslations } from "next-intl";

import { nodeVisual } from "@/components/workflows/node-visuals";
import { ownsAScope } from "@/components/workflows/palette";
import { routesErrors } from "@/lib/workflows/ports";
import { nodeDisplayName, type NodeInstance, type Port } from "@/lib/workflows/types";
import { cn } from "@/lib/utils";
import { useWorkflowEditorStore } from "@/stores/workflow-editor-store";

import { NodeRunStatusLabel } from "@/components/workflows/runs/run-status";

import { useCanvasInteraction } from "./canvas-context";
import { useIsRunView, useNodeRunSummary } from "./run-overlay";
import { isErrorPort, type WorkflowFlowNode } from "./graph-adapter";
import { QuickAdd } from "./quick-add";

type Translate = ReturnType<typeof useTranslations<"workflows">>;

/** One line saying what this step is set up to do, where its config says it plainly. */
export function nodeSummary(instance: NodeInstance, t: Translate): string | null {
  const config = instance.config;
  switch (instance.definition_id) {
    case "logic.if":
      return typeof config.condition === "string" && config.condition ? config.condition : null;
    case "http.request": {
      if (typeof config.url !== "string" || !config.url) return null;
      const method = typeof config.method === "string" ? config.method : "GET";
      try {
        return `${method} ${new URL(config.url).host}`;
      } catch {
        return `${method} ${config.url}`;
      }
    }
    case "error.raise":
      return typeof config.code === "string" && config.code ? config.code : null;
    case "error.handle": {
      const branches = Array.isArray(config.branches) ? config.branches.length : 0;
      return t("nodeSummaryBranches", { count: branches });
    }
    case "logic.switch": {
      const rules = Array.isArray(config.rules) ? config.rules.length : 0;
      return t("nodeSummaryRules", { count: rules });
    }
    case "flow.wait":
      return typeof config.seconds === "number"
        ? t("nodeSummaryWait", { seconds: config.seconds })
        : null;
    case "data.filter":
      return typeof config.condition === "string" && config.condition ? config.condition : null;
    case "control.foreach":
      return config.item_error_policy === "collect"
        ? t("nodeSummaryCollect")
        : t("nodeSummaryStop");
    case "data.map": {
      const mappings = Array.isArray(config.mappings) ? config.mappings.length : 0;
      return mappings > 0 ? t("nodeSummaryMappings", { count: mappings }) : null;
    }
    default:
      return null;
  }
}

/**
 * One workflow node on the canvas - the single component every catalog `kind`
 * bucket renders through (`nodeTypes` maps all three to it).
 *
 * A card: the step's icon and name, a line of what it is set to do, and its
 * output ports as labelled rows with their handles beside them, so a `logic.if`
 * shows which wire is `true`, a loop which is `Each item` and which `Done`, and a
 * step that routes its failures its red `error` port. `Port.kind` places each
 * handle - inputs on the left, outputs on the right - never a port-id
 * convention.
 *
 * Read-only mode (a published version) still mounts every handle - an edge
 * references its ports by id, so with no handle to position against xyflow draws
 * nothing (error 008) - but makes them non-interactive and drops the keyboard
 * connect controls. Beside the pointer-only handles, every output starts and
 * every input completes a keyboard connection through a labelled button, one per
 * port, shown on hover and focus so the card stays quiet otherwise.
 */
export function WorkflowNode({ data, selected }: NodeProps<WorkflowFlowNode>) {
  const t = useTranslations("workflows");
  const { instance, definition, readOnly, bodySize } = data;
  const { connectSource, beginConnect, completeConnect, catalog, insertAfter, problemCounts } =
    useCanvasInteraction();
  const enterScope = useWorkflowEditorStore((state) => state.enterScope);
  const graph = useWorkflowEditorStore((state) => state.graph);

  const kind = definition?.kind ?? "action";
  const scopeOwner = definition !== null && ownsAScope(definition);
  const name = nodeDisplayName(
    definition?.name ?? instance.definition_id,
    instance.id,
    false,
    instance.label,
  );
  const visual = nodeVisual(instance.definition_id, definition?.category ?? "");
  const Icon = visual.icon;
  const inputs: Port[] = definition?.ports.filter((port) => port.kind === "input") ?? [];
  const outputs: Port[] = definition?.ports.filter((port) => port.kind === "output") ?? [];
  const connecting = connectSource !== null;
  const summary = nodeSummary(instance, t);
  // Under the name, what the step is set to do - or else which group it belongs
  // to ("Slack", "Tables"), which a long description would only truncate.
  const category = definition?.category ?? null;
  const group =
    category === null
      ? null
      : category === "triggers"
        ? t("cardTrigger")
        : t.has(`category.${category}`)
          ? t(`category.${category}`)
          : null;
  // A single ordinary output needs no label: the wire leaving the card says it all.
  const labelledOutputs = outputs.length > 1 || outputs.some(isErrorPort);
  const policy = instance.policy ?? null;
  const run = useNodeRunSummary(instance.id);
  const runView = useIsRunView();
  const problems = runView ? 0 : (problemCounts.get(instance.id) ?? 0);

  const connectButton = (port: Port) =>
    !readOnly &&
    !connecting && (
      <button
        type="button"
        aria-label={t("connectFrom", { name, port: port.label })}
        onClick={(event) => {
          // A button on the card, not a click on the node: xyflow would select
          // the node underneath and the selection would outlive what it meant.
          event.stopPropagation();
          beginConnect({ nodeId: instance.id, portId: port.id });
        }}
        className={cn(
          "text-muted-foreground hover:text-foreground hover:bg-accent focus-visible:ring-ring rounded p-0.5 opacity-0 outline-none",
          "group-hover:opacity-100 focus-visible:opacity-100 focus-visible:ring-2",
        )}
      >
        <Cable aria-hidden="true" className="size-3" />
      </button>
    );

  // The "+" beside an output adds the next step there. Shown whenever nothing
  // leaves the port yet - the natural next move - and on hover otherwise.
  const usedPorts = new Set(
    (graph?.edges ?? [])
      .filter((edge) => edge.source_node_id === instance.id)
      .map((edge) => edge.source_port),
  );
  const quickAdd = (port: Port) =>
    !readOnly &&
    !connecting && (
      <span className="absolute top-1/2 -right-8 -translate-y-1/2">
        <QuickAdd
          catalog={catalog}
          nodeName={name}
          portLabel={port.label}
          prominent={!usedPorts.has(port.id)}
          onPick={(next) => insertAfter(instance.id, port.id, next)}
        />
      </span>
    );

  return (
    <div
      data-node-id={instance.id}
      data-node-kind={kind}
      className={cn(
        "group bg-card text-card-foreground relative w-60 rounded-xl border shadow-sm transition-shadow",
        selected ? "ring-primary/60 border-primary/40 ring-2" : "hover:shadow-md",
        run?.status === "failed" && "border-destructive/50 ring-destructive/30 ring-2",
        runView && run === null && "opacity-50",
        // Switched off: still on the canvas, visibly out of the run.
        instance.disabled && "border-dashed opacity-60",
      )}
    >
      {inputs.map((port) => (
        <Handle
          key={port.id}
          id={port.id}
          type="target"
          position={Position.Left}
          isConnectable={!readOnly}
          data-port-id={port.id}
          data-port-variant="input"
          className={cn(
            "!border-background !bg-muted-foreground !size-3 !border-2",
            readOnly && "!pointer-events-none",
          )}
        />
      ))}

      <div className="flex items-start gap-2.5 p-3">
        <span
          className={cn(
            "flex size-8 shrink-0 items-center justify-center rounded-lg",
            visual.tileClass,
          )}
        >
          <Icon aria-hidden="true" className="size-4" />
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline justify-between gap-2">
            <span className="truncate text-sm leading-5 font-medium">{name}</span>
            <span className="flex shrink-0 items-center gap-1">
              {instance.disabled && (
                <span
                  role="img"
                  aria-label={t("stepIsSwitchedOff")}
                  title={t("stepIsSwitchedOff")}
                  className="text-muted-foreground"
                >
                  <CirclePause aria-hidden="true" className="size-3.5" />
                </span>
              )}
              {instance.pinned_output != null && (
                <span
                  role="img"
                  aria-label={t("stepHasPinnedData")}
                  title={t("stepHasPinnedData")}
                  className="text-muted-foreground"
                >
                  <Pin aria-hidden="true" className="size-3.5" />
                </span>
              )}
              {instance.notes && (
                <span
                  role="img"
                  aria-label={t("stepHasNote")}
                  title={instance.notes}
                  className="text-muted-foreground"
                >
                  <StickyNote aria-hidden="true" className="size-3.5" />
                </span>
              )}
              {problems > 0 && (
                <span
                  role="img"
                  aria-label={t("panelWarningCount", { count: problems })}
                  title={t("panelWarningCount", { count: problems })}
                  className="text-destructive"
                >
                  <AlertTriangle aria-hidden="true" className="size-3.5" />
                </span>
              )}
              {!labelledOutputs &&
                outputs.map((port) => <span key={port.id}>{connectButton(port)}</span>)}
            </span>
          </div>
          {(summary ?? group) !== null && (
            <p
              title={definition?.description}
              className={cn(
                "text-muted-foreground truncate text-xs",
                instance.definition_id === "logic.if" && summary !== null && "font-mono",
              )}
            >
              {summary ?? group}
            </p>
          )}
        </div>
      </div>

      {run !== null && (
        <div className="flex items-center justify-between gap-2 px-3 pb-2">
          <NodeRunStatusLabel status={run.status} />
          <span className="text-muted-foreground text-[0.6875rem] tabular-nums">
            {run.runs > 1
              ? t("runIterations", { done: run.succeeded, count: run.runs })
              : run.attempts > 1
                ? t("runAttempts", { count: run.attempts })
                : null}
          </span>
        </div>
      )}
      {run?.problem && (
        <p className="text-destructive line-clamp-2 px-3 pb-2 text-[0.6875rem]">
          {run.problem.message}
        </p>
      )}

      {policy !== null &&
        (policy.timeout_seconds ||
          (policy.retry?.max_attempts ?? 1) > 1 ||
          routesErrors(instance)) && (
          <div className="text-muted-foreground flex flex-wrap gap-1.5 px-3 pb-2 text-[0.6875rem]">
            {policy.timeout_seconds ? (
              <span className="bg-muted inline-flex items-center gap-1 rounded px-1.5 py-0.5">
                <Timer aria-hidden="true" className="size-3" />
                {t("nodeTimeoutBadge", { seconds: policy.timeout_seconds })}
              </span>
            ) : null}
            {(policy.retry?.max_attempts ?? 1) > 1 && (
              <span className="bg-muted inline-flex items-center gap-1 rounded px-1.5 py-0.5">
                <RotateCw aria-hidden="true" className="size-3" />
                {t("nodeRetryBadge", { count: policy.retry?.max_attempts ?? 1 })}
              </span>
            )}
            {routesErrors(instance) && (
              <span className="inline-flex items-center gap-1 rounded bg-rose-500/10 px-1.5 py-0.5 text-rose-700 dark:text-rose-300">
                <ShieldAlert aria-hidden="true" className="size-3" />
                {t("nodeRoutesErrorsBadge")}
              </span>
            )}
          </div>
        )}

      {labelledOutputs ? (
        <ul className="border-border space-y-0.5 border-t py-1.5">
          {outputs.map((port) => (
            <li
              key={port.id}
              className={cn(
                "relative flex items-center justify-end gap-1 px-3 text-xs",
                isErrorPort(port) ? "text-destructive" : "text-muted-foreground",
              )}
            >
              {connectButton(port)}
              <span>{port.label}</span>
              {quickAdd(port)}
              <Handle
                id={port.id}
                type="source"
                position={Position.Right}
                isConnectable={!readOnly}
                data-port-id={port.id}
                data-port-variant={isErrorPort(port) ? "error" : "output"}
                className={cn(
                  "!border-background !size-3 !border-2",
                  isErrorPort(port) ? "!bg-destructive" : "!bg-primary",
                  readOnly && "!pointer-events-none",
                )}
              />
            </li>
          ))}
        </ul>
      ) : (
        outputs.map((port) => (
          <span key={port.id}>
            {quickAdd(port)}
            <Handle
              id={port.id}
              type="source"
              position={Position.Right}
              isConnectable={!readOnly}
              data-port-id={port.id}
              data-port-variant="output"
              className={cn(
                "!border-background !bg-primary !size-3 !border-2",
                readOnly && "!pointer-events-none",
              )}
            />
          </span>
        ))
      )}

      {!readOnly && connecting && connectSource.nodeId !== instance.id && inputs.length > 0 && (
        <div className="border-border flex flex-wrap gap-1 border-t px-3 py-2">
          {inputs.map((port) => (
            <button
              key={port.id}
              type="button"
              aria-label={t("connectTo", { name, port: port.label })}
              onClick={(event) => {
                event.stopPropagation();
                completeConnect(connectSource, { nodeId: instance.id, portId: port.id });
              }}
              className="bg-primary text-primary-foreground rounded-md px-2 py-0.5 text-xs font-medium"
            >
              {t("connectFinish", { port: port.label })}
            </button>
          ))}
        </div>
      )}

      {scopeOwner && (
        <div className="border-border border-t p-2">
          <button
            type="button"
            aria-label={t("enterScope", { name })}
            onClick={(event) => {
              event.stopPropagation();
              enterScope(instance.id);
            }}
            className="hover:bg-accent text-foreground focus-visible:ring-ring flex w-full items-center justify-between rounded-lg px-2 py-1.5 text-xs font-medium outline-none focus-visible:ring-2"
          >
            <span>{readOnly ? t("openScopeLabel") : t("enterScopeLabel")}</span>
            <span className="text-muted-foreground inline-flex items-center gap-1 font-normal">
              {t("scopeStepCount", { count: bodySize })}
              <ArrowUpRight aria-hidden="true" className="size-3.5" />
            </span>
          </button>
        </div>
      )}
    </div>
  );
}

/** Every catalog kind bucket renders through {@link WorkflowNode}. */
export const nodeTypes = {
  action: WorkflowNode,
  control: WorkflowNode,
  waiting: WorkflowNode,
  note: CanvasNoteCard,
};
