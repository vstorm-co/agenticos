"use client";

import { useTranslations } from "next-intl";

import { Button } from "@/components/ui";
import type { ValidationProblem } from "@/components/workflows/validation";
import type { EditorSelection } from "@/stores/workflow-editor-store";
import {
  nodeDisplayName,
  shortNodeId,
  type Binding,
  type NodeCatalog,
  type NodeDefinition,
  type NodeInstance,
  type Uuid,
  type WorkflowEdge,
  type WorkflowGraph,
} from "@/lib/workflows/types";

import { NodeForm } from "./node-form";
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
  upsertBinding,
  removeBinding,
  onSelectNode,
  onDeleteNodes,
}: PanelShellProps) {
  const t = useTranslations("workflows");

  const frame = (title: string, badge: React.ReactNode, body: React.ReactNode) => (
    <section
      aria-label={t("panelTitle")}
      data-workflow-region="property-panel"
      className="border-border space-y-3 rounded-xl border p-4"
    >
      <header className="flex items-center justify-between gap-2">
        <h2 className="text-sm font-medium">{title}</h2>
        {badge}
      </header>
      {body}
    </section>
  );

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
          </>
        )}
        <ProblemsFooter problems={problems} onSelectNode={onSelectNode} />
      </div>,
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
    <div className="space-y-3">
      <p className="text-muted-foreground text-xs">{t("panelEmpty")}</p>
      <ProblemsFooter problems={problems} onSelectNode={onSelectNode} />
    </div>,
  );
}
