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
import { cadenceDraftOf } from "@/components/workflows/property-panel/cadence";
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
import { type ConditionOp, parseCondition, takesNoValue } from "@/lib/workflows/conditions";

type Translate = ReturnType<typeof useTranslations<"workflows">>;

/** A config value that is a list of strings, joined for a card; null when it is not one. */
function names(value: unknown): string | null {
  if (!Array.isArray(value)) return null;
  const strings = value.filter((entry): entry is string => typeof entry === "string" && !!entry);
  return strings.length > 0 ? strings.join(", ") : null;
}

/** What a Transform step does, from its config. */
function transformSummary(instance: NodeInstance, t: Translate): string | null {
  const config = instance.config;
  switch (instance.definition_id) {
    case "transform.limit":
      if (typeof config.count !== "number") return null;
      return t(config.from_end === true ? "nodeSummaryLast" : "nodeSummaryFirst", {
        count: config.count,
      });
    case "transform.sort": {
      const keys = Array.isArray(config.by) ? config.by : [];
      const fields = keys
        .filter(
          (key): key is { field: string; descending?: boolean } =>
            typeof key === "object" && key !== null && typeof key.field === "string",
        )
        .map((key) => (key.descending === true ? `${key.field} ↓` : `${key.field} ↑`));
      return fields.length > 0 ? t("nodeSummarySort", { fields: fields.join(", ") }) : null;
    }
    case "transform.remove_duplicates": {
      const fields = names(config.fields);
      return fields === null ? t("nodeSummaryUnique") : t("nodeSummaryUniqueBy", { fields });
    }
    case "transform.aggregate": {
      const fields = names(config.fields);
      return fields === null ? null : t("nodeSummaryAggregate", { fields });
    }
    case "transform.split_out":
      return typeof config.field === "string" && config.field
        ? t("nodeSummarySplitOut", { field: config.field })
        : null;
    case "transform.summarize": {
      const [first] = Array.isArray(config.summaries) ? config.summaries : [];
      if (typeof first !== "object" || first === null || typeof first.operation !== "string") {
        return null;
      }
      const what = t(`nodeSummaryOperation.${first.operation}`, { field: first.field ?? "" });
      const groups = names(config.group_by);
      return groups === null ? what : t("nodeSummaryGrouped", { what, groups });
    }
    case "transform.edit_fields": {
      const set = Array.isArray(config.set) ? config.set.length : 0;
      return set > 0 ? t("nodeSummarySets", { count: set }) : null;
    }
    case "transform.date_time": {
      const operation = typeof config.operation === "string" ? config.operation : "now";
      if (operation === "add" || operation === "subtract") {
        const amount = typeof config.amount === "number" ? config.amount : 0;
        const unit = typeof config.unit === "string" ? config.unit : "days";
        const span = t(`nodeSummaryUnit.${unit}`, { count: amount });
        return t(operation === "add" ? "nodeSummaryAdds" : "nodeSummarySubtracts", { span });
      }
      return t(operation === "format" ? "nodeSummaryFormats" : "nodeSummaryNow");
    }
    case "transform.crypto":
      return typeof config.operation === "string"
        ? t(`nodeSummaryCrypto.${config.operation}`)
        : null;
    default:
      return null;
  }
}

const CONDITION_ROOT: Record<string, "item" | "value"> = {
  "data.filter": "item",
  "logic.if": "value",
};

const OP_SIGN: Partial<Record<ConditionOp, string>> = {
  eq: "=",
  ne: "≠",
  gt: ">",
  gte: "≥",
  lt: "<",
  lte: "≤",
};

/**
 * A condition as a card reads it - "score ≥ 80 and stage ≠ Won" - when the
 * builder could have written it; otherwise null, and the card shows the
 * expression itself.
 */
function conditionSummary(expression: string, root: "item" | "value", t: Translate): string | null {
  const condition = parseCondition(expression, root);
  if (condition === null) return null;
  const rows = condition.rows.map((row) => {
    const field = row.field || root;
    const sign = OP_SIGN[row.op];
    if (sign !== undefined) return `${field} ${sign} ${row.value}`;
    const words = t(`conditionOps.${row.op}`);
    return takesNoValue(row.op) ? `${field} ${words}` : `${field} ${words} ${row.value}`;
  });
  return rows.join(t(condition.join === "and" ? "nodeSummaryAnd" : "nodeSummaryOr"));
}

/** Whether a card's summary is an expression - a condition, a crontab - set in monospace. */
function summaryIsCode(instance: NodeInstance): boolean {
  const root = CONDITION_ROOT[instance.definition_id];
  if (root !== undefined) {
    const condition = instance.config.condition;
    return typeof condition === "string" && parseCondition(condition, root) === null;
  }
  return (
    instance.definition_id === "trigger.schedule" && cadenceDraftOf(instance.config).mode === "cron"
  );
}

/** When a Schedule trigger fires, from its cadence. */
function scheduleSummary(config: Record<string, unknown>, t: Translate): string {
  const draft = cadenceDraftOf(config);
  if (draft.mode === "daily") return t("nodeSummaryDaily", { time: draft.time });
  if (draft.mode === "cron") return draft.cron;
  return t(`nodeSummaryEvery.${draft.unit}`, { count: Number(draft.count) });
}

/** One line saying what this step is set up to do, where its config says it plainly. */
export function nodeSummary(instance: NodeInstance, t: Translate): string | null {
  const config = instance.config;
  switch (instance.definition_id) {
    case "logic.if":
    case "data.filter": {
      const condition = config.condition;
      if (typeof condition !== "string" || !condition) return null;
      return (
        conditionSummary(condition, CONDITION_ROOT[instance.definition_id] as "item", t) ??
        condition
      );
    }
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
      if (config.until_called === true) return t("nodeSummaryWaitCall");
      return typeof config.seconds === "number"
        ? t("nodeSummaryWait", { seconds: config.seconds })
        : null;
    case "control.foreach":
      return config.item_error_policy === "collect"
        ? t("nodeSummaryCollect")
        : t("nodeSummaryStop");
    case "data.map": {
      const mappings = Array.isArray(config.mappings) ? config.mappings.length : 0;
      return mappings > 0 ? t("nodeSummaryMappings", { count: mappings }) : null;
    }
    case "trigger.schedule":
      return scheduleSummary(config, t);
    default:
      return transformSummary(instance, t);
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
  const {
    connectSource,
    beginConnect,
    completeConnect,
    catalog,
    insertAfter,
    problemCounts,
    changes,
  } = useCanvasInteraction();
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
  // Under the name, what the step is set to do - or else, for a step given a
  // name of its own, what kind of step it is ("Limit"), or which group it
  // belongs to ("Slack", "Tables"), which a long description would only truncate.
  const category = definition?.category ?? null;
  const group =
    instance.label && definition !== null
      ? definition.name
      : category === null
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
  const change = changes?.get(instance.id) ?? null;

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
        change === "added" && "border-emerald-500/60 ring-2 ring-emerald-500/25",
        change === "removed" && "border-destructive/50 border-dashed opacity-70",
        change === "changed" && "border-foreground/40 ring-foreground/15 ring-2",
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
              {change !== null && (
                <span
                  className={cn(
                    "rounded px-1.5 text-[10px] font-medium tracking-wide uppercase",
                    change === "added" &&
                      "bg-emerald-500/10 text-emerald-700 dark:text-emerald-400",
                    change === "removed" && "bg-destructive/10 text-destructive",
                    change === "changed" && "bg-muted text-foreground",
                  )}
                >
                  {t(`diff.${change}`)}
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
                summary !== null && summaryIsCode(instance) && "font-mono",
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
