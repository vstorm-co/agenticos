"use client";

import { useTranslations } from "next-intl";

import { Button } from "@/components/ui";
import { nodeVisual } from "@/components/workflows/node-visuals";
import { cn } from "@/lib/utils";
import type { ValidationProblem } from "@/components/workflows/validation";
import type { EditorSelection } from "@/stores/workflow-editor-store";
import {
  nodeDisplayName,
  shortNodeId,
  type Binding,
  type NodeCatalog,
  type NodeDefinition,
  type NodeInstance,
  type NodePolicy,
  type Uuid,
  type WorkflowEdge,
  type WorkflowGraph,
} from "@/lib/workflows/types";

import { NodeForm } from "./node-form";
import { PolicySection } from "./policy-section";
import {
  fieldErrors,
  nodeLevelProblems,
  nodeProblemCount,
  ProblemsFooter,
  WarningBadge,
} from "./problems";

/** The catalog definition a node instance pins, or null when the catalog lacks it. */
function findDefinition(catalog: NodeCatalog, node: NodeInstance): NodeDefinition | null {
  return (
    catalog.items.find(
      (definition) =>
        definition.id === node.definition_id && definition.version === node.definition_version,
    ) ?? null
  );
}

/** A node's display name: its definition's name where known, else its definition id, with a short id. */
function nodeLabel(graph: WorkflowGraph, catalog: NodeCatalog, nodeId: Uuid): string {
  const node = graph.nodes.find((candidate) => candidate.id === nodeId);
  if (node === undefined) return shortNodeId(nodeId);
  const definition = findDefinition(catalog, node);
  return definition !== null
    ? nodeDisplayName(definition.name, nodeId, true)
    : nodeDisplayName(node.definition_id, nodeId, true);
}

export interface PanelShellProps {
  /** The graph being edited, or null before one loads. */
  graph: WorkflowGraph | null;
  /** The single selected node the store resolved, or null. */
  selectedNode: NodeInstance | null;
  /** What the canvas has selected. */
  selection: EditorSelection;
  catalog: NodeCatalog;
  /** Every client-side problem in the graph, already translated. */
  problems: ValidationProblem[];
  disabled?: boolean;
  updateNodeConfig: (nodeId: Uuid, config: Record<string, unknown>) => void;
  updateNodePolicy: (nodeId: Uuid, policy: NodePolicy | null) => void;
  upsertBinding: (binding: Binding) => void;
  removeBinding: (targetNodeId: Uuid, targetField: string) => void;
  /** Select a node from a problem link. */
  onSelectNode: (nodeId: Uuid) => void;
  /** Bulk-delete the multi-selection, when the host wires it. */
  onDeleteNodes?: (nodeIds: Uuid[]) => void;
}

/** The docked right-hand panel: header, the form, and the empty/multi/edge states. */
export function PanelShell({
  graph,
  selectedNode,
  selection,
  catalog,
  problems,
  disabled,
  updateNodeConfig,
  updateNodePolicy,
  upsertBinding,
  removeBinding,
  onSelectNode,
  onDeleteNodes,
}: PanelShellProps) {
  const t = useTranslations("workflows");

  const frame = (
    title: string,
    badge: React.ReactNode,
    body: React.ReactNode,
    node?: { definition: NodeDefinition | null; instance: NodeInstance },
  ) => {
    const visual =
      node === undefined
        ? null
        : nodeVisual(node.instance.definition_id, node.definition?.category ?? "");
    const Icon = visual?.icon;
    return (
      <section
        aria-label={t("panelTitle")}
        data-workflow-region="property-panel"
        className="space-y-4 p-4"
      >
        <header className="flex items-start justify-between gap-2">
          <div className="flex min-w-0 items-start gap-2.5">
            {visual !== null && Icon !== undefined && (
              <span
                className={cn(
                  "flex size-8 shrink-0 items-center justify-center rounded-lg",
                  visual.tileClass,
                )}
              >
                <Icon aria-hidden="true" className="size-4" />
              </span>
            )}
            <div className="min-w-0">
              <h2 className="truncate text-sm font-medium">{title}</h2>
              {node?.definition && (
                <p className="text-muted-foreground text-xs">{node.definition.description}</p>
              )}
            </div>
          </div>
          {badge}
        </header>
        {body}
      </section>
    );
  };

  if (graph === null) {
    return frame(
      t("panelTitle"),
      null,
      <p className="text-muted-foreground text-xs">{t("panelEmpty")}</p>,
    );
  }

  const { nodeIds, edgeIds } = selection;

  if (nodeIds.length > 1) {
    return frame(
      t("panelMultiTitle"),
      null,
      <div className="space-y-3">
        <p className="text-muted-foreground text-xs">
          {t("panelMultiSelected", { count: nodeIds.length })}
        </p>
        {onDeleteNodes !== undefined && (
          <Button
            type="button"
            variant="destructive"
            size="sm"
            disabled={disabled}
            onClick={() => onDeleteNodes(nodeIds)}
          >
            {t("panelBulkDelete")}
          </Button>
        )}
        <ProblemsFooter problems={problems} onSelectNode={onSelectNode} />
      </div>,
    );
  }

  if (nodeIds.length === 1 && selectedNode !== null) {
    const definition = findDefinition(catalog, selectedNode);
    const title =
      definition !== null
        ? nodeDisplayName(definition.name, selectedNode.id, true)
        : nodeDisplayName(selectedNode.definition_id, selectedNode.id, true);
    const nodeProblems = nodeLevelProblems(problems, selectedNode.id);
    return frame(
      title,
      <WarningBadge count={nodeProblemCount(problems, selectedNode.id)} />,
      <div className="space-y-4">
        {definition === null ? (
          <p className="text-muted-foreground text-xs">{t("panelUnknownDefinition")}</p>
        ) : (
          <>
            {nodeProblems.length > 0 && (
              <ul className="space-y-1">
                {nodeProblems.map((problem, index) => (
                  <li key={index} className="text-destructive text-xs">
                    {problem.message}
                  </li>
                ))}
              </ul>
            )}
            <NodeForm
              definition={definition}
              node={selectedNode}
              graph={graph}
              catalog={catalog}
              bindings={graph.bindings}
              errors={fieldErrors(problems, selectedNode.id)}
              disabled={disabled}
              updateNodeConfig={updateNodeConfig}
              upsertBinding={upsertBinding}
              removeBinding={removeBinding}
            />
            {selectedNode.definition_id !== "loop.item" && (
              <div className="border-border border-t pt-4">
                <PolicySection
                  definition={definition}
                  node={selectedNode}
                  disabled={disabled}
                  updateNodePolicy={updateNodePolicy}
                />
              </div>
            )}
          </>
        )}
        <ProblemsFooter problems={problems} onSelectNode={onSelectNode} />
      </div>,
      { definition, instance: selectedNode },
    );
  }

  if (nodeIds.length === 0 && edgeIds.length === 1) {
    const edge: WorkflowEdge | undefined = graph.edges.find(
      (candidate) => candidate.id === edgeIds[0],
    );
    if (edge !== undefined) {
      return frame(
        t("panelEdgeTitle"),
        null,
        <div className="space-y-3">
          <div className="space-y-2 text-xs">
            <div>
              <span className="text-muted-foreground">{t("panelEdgeFrom")}</span>{" "}
              {nodeLabel(graph, catalog, edge.source_node_id)} · {edge.source_port}
            </div>
            <div>
              <span className="text-muted-foreground">{t("panelEdgeTo")}</span>{" "}
              {nodeLabel(graph, catalog, edge.target_node_id)} · {edge.target_port}
            </div>
          </div>
          <ProblemsFooter problems={problems} onSelectNode={onSelectNode} />
        </div>,
      );
    }
  }

  return frame(
    t("panelTitle"),
    null,
    <div className="space-y-4">
      <p className="text-muted-foreground text-xs">{t("panelEmpty")}</p>
      <dl className="grid grid-cols-2 gap-2">
        {[
          { label: t("panelStepCount"), value: graph.nodes.length },
          { label: t("panelConnectionCount"), value: graph.edges.length },
        ].map((figure) => (
          <div key={figure.label} className="bg-muted/50 rounded-lg px-3 py-2">
            <dt className="text-muted-foreground text-xs">{figure.label}</dt>
            <dd className="text-lg font-medium tabular-nums">{figure.value}</dd>
          </div>
        ))}
      </dl>
      {problems.length === 0 ? (
        <p className="text-muted-foreground text-xs">{t("panelNoProblems")}</p>
      ) : (
        <ProblemsFooter problems={problems} onSelectNode={onSelectNode} defaultOpen />
      )}
    </div>,
  );
}
