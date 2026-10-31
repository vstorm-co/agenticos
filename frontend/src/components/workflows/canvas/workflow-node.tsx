"use client";

import {
  Handle,
  NodeResizeControl,
  type NodeProps,
  Position,
  ResizeControlVariant,
} from "@xyflow/react";
import { CanvasNoteCard } from "./canvas-note";
import {
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

import { NodeTile } from "@/components/workflows/node-tile";
import { familyLabelClass, nodeFamily } from "@/components/workflows/node-visuals";
import { appToolLabel } from "@/components/workflows/apps";
import { connectionLabel } from "@/lib/mcp-servers";
import { type McpAppStep, useMcpAppStep } from "@/components/workflows/use-app-connections";
import { cadenceDraftOf } from "@/components/workflows/property-panel/cadence";
import { ownsAScope } from "@/components/workflows/palette";
import { routesErrors, splitBranches } from "@/lib/workflows/ports";
import { nodeDisplayName, type NodeInstance, type Port } from "@/lib/workflows/types";
import { cn } from "@/lib/utils";
import { useWorkflowEditorStore } from "@/stores/workflow-editor-store";
import { useWorkflowNodeStyleStore } from "@/stores/workflow-node-style-store";

import { useCanvasInteraction } from "./canvas-context";
import { AgentTile, InlineAgentTile, ResourceLine, resourcePin } from "./node-resource";
import { type NodeRunState, useNodeRunState } from "./run-overlay";
import { RunPill } from "./run-pill";
import { isErrorPort, type WorkflowFlowNode } from "./graph-adapter";
import { ProblemBadge } from "./problem-badge";
import { QuickAdd } from "./quick-add";
import { QuickLogControl } from "./quick-log";
import {
  cardHeight,
  MAX_NODE_HEIGHT,
  MAX_NODE_WIDTH,
  MIN_NODE_WIDTH,
  textLines,
} from "./node-size";
import { waitsBand } from "./waits-band";
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

/**
 * How many tries the policy badge announces. A run's canvas says what happened
 * instead (`runAttempts`, once, under the card): the policy's ceiling beside it
 * reads as if every try had been used.
 */
function retryBadgeTries(policy: NonNullable<NodeInstance["policy"]>, run: unknown): number {
  return run === null ? (policy.retry?.max_attempts ?? 1) : 1;
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
    case "mcp.call":
      return typeof config.tool === "string" && config.tool ? config.tool : null;
    case "error.handle": {
      const branches = Array.isArray(config.branches) ? config.branches.length : 0;
      return t("nodeSummaryBranches", { count: branches });
    }
    case "logic.split":
      return t("nodeSummarySplitBranches", { count: splitBranches(config).length });
    case "logic.switch": {
      const rules = Array.isArray(config.rules) ? config.rules.length : 0;
      return t("nodeSummaryRules", { count: rules });
    }
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
 * A step's card on a run's canvas, by what the run did with it: amber and
 * dashed while it waits its turn, green while it runs and once done, rose
 * while a person decides, red when it failed, faded when the run never came to it.
 */
const RUN_CARD: Record<NodeRunState, string> = {
  pending: "border-warning border-dashed",
  starting: "border-success",
  running: "border-success",
  waiting: "border-[var(--domain-admin)]",
  done: "border-success/60",
  failed: "border-destructive border-2",
  attention: "border-destructive border-2",
  skipped: "border-dotted opacity-40",
  notReached: "opacity-50",
};

/**
 * The rings of a run's states, apart from the borders: with a quick log's strip
 * docked they are drawn on an overlay around the card and the strip together.
 */
const RUN_RING: Partial<Record<NodeRunState, string>> = {
  starting: "ring-success/15 ring-4",
  running: "ring-success/15 ring-4",
  waiting: "ring-2 ring-[var(--domain-admin-line)]",
  failed: "ring-destructive/15 ring-4",
  attention: "ring-destructive/15 ring-4",
};

/** How a card's name and summary are cut once they pass the lines the card gives them. */
const NAME_LINES = { 1: "truncate", 2: "line-clamp-2 break-words", 3: "line-clamp-3 break-words" };
const SUMMARY_LINES = { 1: "truncate", 2: "line-clamp-2 break-words" };

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
export function WorkflowNode(props: NodeProps<WorkflowFlowNode>) {
  // Only an MCP call asks which app its connection belongs to: no other card needs the list.
  return props.data.instance.definition_id === "mcp.call" ? (
    <McpWorkflowNode {...props} />
  ) : (
    <WorkflowCard {...props} mcp={null} />
  );
}

function McpWorkflowNode(props: NodeProps<WorkflowFlowNode>) {
  return <WorkflowCard {...props} mcp={useMcpAppStep(props.data.instance.config)} />;
}

function WorkflowCard({
  data,
  selected,
  height,
  mcp,
}: NodeProps<WorkflowFlowNode> & { mcp: McpAppStep | null }) {
  const t = useTranslations("workflows");
  const { instance, definition, readOnly, bodySize } = data;
  const {
    connectSource,
    beginConnect,
    completeConnect,
    catalog,
    insertAfter,
    problemTexts,
    changes,
  } = useCanvasInteraction();
  const problemsRevealed = useWorkflowEditorStore((state) => state.problemsRevealed);
  const enterScope = useWorkflowEditorStore((state) => state.enterScope);
  const editNode = useWorkflowEditorStore((state) => state.editNode);
  const graph = useWorkflowEditorStore((state) => state.graph);

  const kind = definition?.kind ?? "action";
  const scopeOwner = definition !== null && ownsAScope(definition);
  // A call on an app's connection reads as that app's action - "Gmail · Create draft" -
  // and still says it is an MCP call: a badge, and its connection and raw tool below.
  const mcpAction =
    mcp === null || mcp.tool === ""
      ? null
      : t("appCardName", {
          app: t(`category.${mcp.app.id}`),
          tool: appToolLabel(mcp.app, mcp.tool, t),
        });
  const name =
    instance.label || mcpAction === null
      ? nodeDisplayName(
          definition?.name ?? instance.definition_id,
          instance.id,
          false,
          instance.label,
        )
      : mcpAction;
  const style = useWorkflowNodeStyleStore((state) => state.style);
  const family = nodeFamily(definition?.category ?? "");
  const band = waitsBand(instance, graph?.bindings ?? []);
  const inputs: Port[] = definition?.ports.filter((port) => port.kind === "input") ?? [];
  const outputs: Port[] = definition?.ports.filter((port) => port.kind === "output") ?? [];
  const connecting = connectSource !== null;
  const summary =
    mcp === null || mcp.tool === ""
      ? nodeSummary(instance, t)
      : t("appCardSubtitle", { connection: connectionLabel(mcp.connection), tool: mcp.tool });
  // Sized by a person: the card then fills the box xyflow gives the node, and the
  // height above what the card needs goes to its text.
  const { width: sizedWidth, height: sizedHeight } = instance.layout;
  const pin = resourcePin(instance);
  const natural = cardHeight(
    instance,
    definition,
    graph?.bindings ?? [],
    summary !== null || pin !== null,
  );
  const lines = textLines(sizedHeight, natural);
  const resizable = selected && !readOnly;
  // Until it is sized the card is what xyflow measured, to the pixel, wrapped
  // badges and all; once sized, `height` is the box, so the floor is the estimate.
  const floor = sizedHeight == null && height ? height : natural;
  const tile = (
    <NodeTile
      {...(mcp === null
        ? { definitionId: instance.definition_id, category: definition?.category ?? "" }
        : { kind: "group" as const, category: mcp.app.id })}
      className="size-8 rounded-lg"
      iconClassName="size-4"
    />
  );
  // Above the name, "Family · Kind": what sort of step it is, whatever it is called.
  // A step still called by its kind's own name would say the kind twice: family alone.
  const kindName = definition?.name ?? instance.definition_id;
  const cardLabel =
    name === kindName
      ? t(`family.${family}`)
      : t("cardLabel", { family: t(`family.${family}`), kind: kindName });
  // A single ordinary output needs no label: the wire leaving the card says it all.
  const labelledOutputs = outputs.length > 1 || outputs.some(isErrorPort);
  const policy = instance.policy ?? null;
  const runState = useNodeRunState(instance.id);
  const run = runState?.summary ?? null;
  const runView = runState !== null;
  const crashed = runState?.state === "failed" || runState?.state === "attention";
  const problems = runView ? [] : (problemTexts.get(instance.id) ?? []);
  const change = changes?.get(instance.id) ?? null;
  // The ports a quick log writes for, null when the step has none.
  const logged =
    instance.quick_log == null
      ? null
      : new Set(instance.quick_log.outputs ?? outputs.map((port) => port.id));

  // Every ring the card draws - selected, the run's, the change's - as one set, so
  // a docked strip can be wrapped by them with the card instead of left outside.
  const ring = cn(
    selected && "ring-primary/60 ring-2",
    runState !== null && RUN_RING[runState.state],
    change === "added" && "ring-2 ring-emerald-500/25",
    change === "changed" && "ring-2 ring-[var(--domain-use-line)]",
  );

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
  // `beyondStrip`: placed against the card itself, so past a docked quick-log strip.
  const quickAdd = (port: Port, beyondStrip = false) =>
    !readOnly &&
    !connecting && (
      <span
        className={cn(
          "absolute top-1/2 -translate-y-1/2",
          beyondStrip ? "-right-[53px]" : "-right-8",
        )}
      >
        <QuickAdd
          catalog={catalog}
          nodeName={name}
          portLabel={port.label}
          prominent={!usedPorts.has(port.id)}
          onPick={(next, config) => insertAfter(instance.id, port.id, next, config)}
        />
      </span>
    );

  return (
    <div
      data-node-id={instance.id}
      data-node-kind={kind}
      data-node-family={family}
      className={cn(
        "group bg-card text-card-foreground relative rounded-xl border shadow-sm transition-shadow",
        sizedWidth == null ? "w-60" : "w-full",
        // A quick log's strip is docked to the right side: the card's corners there give way to it.
        logged !== null && "rounded-r-none",
        // Taller than it needs: the ports sit at the bottom, the text at the top. A row
        // the estimate misses (Connect to, run counts) grows the card, never spills out.
        sizedHeight != null && "flex min-h-full flex-col",
        // A run starts here: the card's left end is rounded like a start cap, in either style.
        family === "start" && "rounded-l-[2rem]",
        selected ? "border-primary/40" : "hover:shadow-md",
        // Beside a docked strip the rings go on the overlay below, around both.
        logged === null && ring,
        runState !== null && RUN_CARD[runState.state],
        // Moving only while it is watched: a run opened once it ended is still.
        runState?.watched &&
          (runState.state === "running" || runState.state === "starting") &&
          "run-breathe",
        runState?.watched && crashed && "run-crash",
        // Switched off: still on the canvas, visibly out of the run.
        instance.disabled && "border-dashed opacity-60",
        change === "added" && "border-emerald-500/60",
        change === "removed" && "border-destructive/50 border-dashed opacity-70",
        // Blue, the one hue no family and no selection uses, so "changed" never reads as either.
        change === "changed" && "border-[var(--domain-use)]",
      )}
    >
      {logged !== null && ring !== "" && (
        // One rounded outline around the card and its strip, with no seam: the strip's
        // 20px past the card's own edge.
        <span
          aria-hidden="true"
          data-testid="card-ring"
          className={cn("pointer-events-none absolute -inset-px -right-5 rounded-xl", ring)}
        />
      )}
      {/* A step the catalog does not know has no outputs to log. */}
      {(definition !== null || instance.quick_log != null) && (
        <QuickLogControl instance={instance} outputs={outputs} name={name} readOnly={readOnly} />
      )}
      {resizable && (
        // First, so the handles painted after it stay on top of its edges.
        <>
          <NodeResizeControl
            position="right"
            variant={ResizeControlVariant.Line}
            resizeDirection="horizontal"
            minWidth={MIN_NODE_WIDTH}
            maxWidth={MAX_NODE_WIDTH}
            // The edges drag but draw nothing: the corner square is the one visible
            // handle, and the resize cursor says an edge can be pulled too.
            color="transparent"
            // Wide to grab, on the card's own edge: xyflow centres the box on it.
            style={{ width: 8, transform: "translate(calc(-100% + 0.5px), 0)" }}
          />
          <NodeResizeControl
            position="bottom"
            variant={ResizeControlVariant.Line}
            resizeDirection="vertical"
            minHeight={floor}
            maxHeight={Math.max(MAX_NODE_HEIGHT, floor)}
            color="transparent"
            style={{ height: 8, transform: "translate(0, calc(-100% + 0.5px))" }}
          />
          <NodeResizeControl
            position="bottom-right"
            minWidth={MIN_NODE_WIDTH}
            maxWidth={MAX_NODE_WIDTH}
            minHeight={floor}
            maxHeight={Math.max(MAX_NODE_HEIGHT, floor)}
            color="var(--color-primary)"
            style={{ width: 9, height: 9 }}
          />
        </>
      )}
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

      {band !== null && (
        <div
          role="note"
          aria-label={t("waits.label", { what: t(`waits.${band.key}`, band.values) })}
          className={cn(
            "flex h-[22px] items-center gap-1.5 px-3 text-[11px] font-semibold",
            // Square where a docked strip meets the card, as the card's own corners are.
            logged !== null ? "rounded-tl-[11px]" : "rounded-t-[11px]",
            band.tone === "person" && style === "colour"
              ? "bg-[var(--domain-admin-subtle)] text-[var(--domain-admin)]"
              : "bg-muted text-foreground",
          )}
        >
          <band.icon aria-hidden="true" className="size-3 shrink-0" />
          <span className="truncate">{t(`waits.${band.key}`, band.values)}</span>
        </div>
      )}
      <div className={cn("flex items-start gap-2.5 p-3", family === "start" && "pl-3.5")}>
        {pin?.kind === "agent" ? (
          <AgentTile agentId={pin.id} fallback={tile} />
        ) : pin?.kind === "inline_agent" ? (
          <InlineAgentTile name={pin.name} />
        ) : (
          tile
        )}
        <div className="min-w-0 flex-1">
          <p
            title={definition?.description}
            className={cn(
              "truncate text-[10.5px] leading-[14px] font-semibold tracking-[0.06em] uppercase",
              familyLabelClass(family, style),
            )}
          >
            {cardLabel}
          </p>
          <div className="flex items-baseline justify-between gap-2">
            <span
              className={cn(
                "text-sm leading-5 font-medium",
                // An app's action reads in full: the tool is what tells two cards apart.
                mcpAction !== null && !instance.label ? "break-words" : NAME_LINES[lines.name],
              )}
            >
              {name}
            </span>
            <span className="flex shrink-0 items-center gap-1">
              {mcp !== null && (
                <span
                  title={t("appMcpBadgeHint")}
                  className="text-muted-foreground border-border rounded border px-1 text-[10px] font-medium tracking-wide"
                >
                  {t("appMcpBadge")}
                </span>
              )}
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
                    change === "changed" &&
                      "bg-[var(--domain-use-subtle)] text-[var(--domain-use)]",
                  )}
                >
                  {t(`diff.${change}`)}
                </span>
              )}
              {problems.length > 0 && (
                <ProblemBadge
                  revealed={problemsRevealed}
                  problems={problems}
                  onOpen={() => editNode(instance.id)}
                />
              )}
              {!labelledOutputs &&
                outputs.map((port) => <span key={port.id}>{connectButton(port)}</span>)}
            </span>
          </div>
          {(summary !== null || pin !== null) && (
            <p
              title={definition?.description}
              className={cn(
                "text-muted-foreground text-xs",
                mcp !== null && mcp.tool !== "" ? "break-words" : SUMMARY_LINES[lines.summary],
                summary !== null && summaryIsCode(instance) && "font-mono",
              )}
            >
              {pin !== null && (
                // Empty while the name loads or for one the caller cannot see: no dangling dot.
                <span
                  className={cn(
                    "empty:hidden",
                    summary !== null && "after:mx-1 after:content-['·']",
                  )}
                >
                  <ResourceLine pin={pin} fallback={null} />
                </span>
              )}
              {summary}
            </p>
          )}
        </div>
      </div>

      {runState !== null && <RunPill state={runState.state} summary={run} />}
      {run !== null && (run.runs > 1 || run.attempts > 1) && (
        <p className="text-muted-foreground px-3 pb-2 text-[0.6875rem] tabular-nums">
          {run.runs > 1
            ? t("runIterations", { done: run.succeeded, count: run.runs })
            : t("runAttempts", { count: run.attempts })}
        </p>
      )}
      {crashed && run?.problem && (
        // Under the card, where it cannot be missed: the step's own error.
        <div
          role="alert"
          className="border-destructive/40 bg-destructive/10 absolute inset-x-0 top-full mt-2 rounded-lg border px-2.5 py-1.5 text-[0.6875rem] leading-snug"
        >
          <span className="text-destructive block font-mono text-[0.625rem] font-semibold">
            {run.problem.code}
          </span>
          <span className="line-clamp-3">{run.problem.message}</span>
        </div>
      )}

      {policy !== null &&
        (policy.timeout_seconds || retryBadgeTries(policy, run) > 1 || routesErrors(instance)) && (
          <div className="text-muted-foreground flex flex-wrap gap-1.5 px-3 pb-2 text-[0.6875rem]">
            {policy.timeout_seconds ? (
              <span className="bg-muted inline-flex items-center gap-1 rounded px-1.5 py-0.5">
                <Timer aria-hidden="true" className="size-3" />
                {t("nodeTimeoutBadge", { seconds: policy.timeout_seconds })}
              </span>
            ) : null}
            {retryBadgeTries(policy, run) > 1 && (
              <span className="bg-muted inline-flex items-center gap-1 rounded px-1.5 py-0.5">
                <RotateCw aria-hidden="true" className="size-3" />
                {t("nodeRetryBadge", { count: retryBadgeTries(policy, run) })}
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
        <ul className="border-border mt-auto space-y-0.5 border-t py-1.5">
          {outputs.map((port) => (
            <li
              key={port.id}
              className={cn(
                // Under a quick log the row reaches across the docked strip (20px and its
                // border), so the handle and the "+" sit on the strip's outer edge.
                "relative flex items-center justify-end gap-1 pl-3 text-xs",
                logged === null ? "pr-3" : "-mr-[21px] pr-[33px]",
                isErrorPort(port) ? "text-destructive" : "text-muted-foreground",
              )}
            >
              {connectButton(port)}
              {logged?.has(port.id) && (
                // In the LOG strip, on this output's row, at the card's side: a bar, so it is
                // never read as a second handle.
                <span
                  role="img"
                  aria-label={t("quickLogMark")}
                  title={t("quickLogMark")}
                  className="bg-primary absolute right-[13px] h-0.5 w-1.5 rounded-full"
                />
              )}
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
            {quickAdd(port, logged !== null)}
            <Handle
              id={port.id}
              type="source"
              position={Position.Right}
              isConnectable={!readOnly}
              // On the docked strip's outer edge, as the labelled rows' handles are.
              style={logged === null ? undefined : { right: -21 }}
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
