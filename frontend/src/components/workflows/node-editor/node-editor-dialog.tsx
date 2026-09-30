"use client";

import { useMemo } from "react";
import { Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button, Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui";
import { nodeVisual } from "@/components/workflows/node-visuals";
import { NodeForm } from "@/components/workflows/property-panel/node-form";
import { PolicySection } from "@/components/workflows/property-panel/policy-section";
import { StepDetails } from "./step-details";
import {
  WarningBadge,
  fieldErrors,
  nodeLevelProblems,
  nodeNames,
  nodeProblemCount,
} from "@/components/workflows/property-panel/problems";
import { usePanelStore } from "@/components/workflows/property-panel/store-bridge";
import { validateGraph } from "@/components/workflows/validation";
import { cn } from "@/lib/utils";
import { isTrigger } from "@/lib/workflows/triggers";
import type { NodeCatalog, NodeDefinition } from "@/lib/workflows/types";

interface NodeEditorDialogProps {
  catalog: NodeDefinition[];
  /** A version or a workflow the caller may not edit: every field reads, none writes. */
  readOnly?: boolean;
}

/**
 * One step's settings, in a dialog over the canvas - opened by clicking the
 * step, or by adding one that has anything to set.
 *
 * The whole width goes to the step: its settings, what it reads from earlier
 * steps, and what happens when it is slow or fails, with each problem that stops
 * a publish beside the field it is about. Every edit is written to the draft as
 * it is made, so there is nothing to save - **Done** only closes.
 */
export function NodeEditorDialog({ catalog, readOnly = false }: NodeEditorDialogProps) {
  const t = useTranslations("workflows");
  const store = usePanelStore();
  const graph = store.graph;
  const node = graph?.nodes.find((candidate) => candidate.id === store.editingNodeId) ?? null;
  const catalogIndex: NodeCatalog = useMemo(
    () => ({ items: catalog, total: catalog.length }),
    [catalog],
  );
  const problems = useMemo(
    () => (graph === null ? [] : validateGraph(graph, catalogIndex, t)),
    [graph, catalogIndex, t],
  );

  const close = () => store.editNode(null);
  const definition =
    node === null
      ? null
      : (catalog.find(
          (item) => item.id === node.definition_id && item.version === node.definition_version,
        ) ?? null);

  if (graph === null || node === null) return null;
  const visual = nodeVisual(node.definition_id, definition?.category ?? "");
  const Icon = visual.icon;
  const nodeProblems = nodeLevelProblems(problems, node.id);

  return (
    <Dialog open onOpenChange={(open) => !open && close()}>
      <DialogContent className="flex max-h-[88vh] max-w-2xl flex-col gap-0 p-0">
        <header className="border-border flex items-start gap-3 border-b px-6 pt-6 pr-14 pb-4">
          <span
            className={cn(
              "flex size-10 shrink-0 items-center justify-center rounded-xl",
              visual.tileClass,
            )}
          >
            <Icon aria-hidden="true" className="size-5" />
          </span>
          <div className="min-w-0 flex-1 space-y-1">
            <div className="flex items-center gap-2">
              <DialogTitle className="truncate text-base">
                {nodeNames(graph, catalogIndex).get(node.id) ?? node.definition_id}
              </DialogTitle>
              <WarningBadge count={nodeProblemCount(problems, node.id)} />
            </div>
            <DialogDescription className="text-sm">
              {definition?.description ?? t("panelUnknownDefinition")}
            </DialogDescription>
          </div>
        </header>
        <div className="min-h-0 flex-1 space-y-5 overflow-y-auto px-6 py-5">
          {nodeProblems.length > 0 && (
            <ul className="bg-destructive/5 border-destructive/20 space-y-1 rounded-lg border px-3 py-2">
              {nodeProblems.map((problem, index) => (
                <li key={index} className="text-destructive text-sm">
                  {problem.message}
                </li>
              ))}
            </ul>
          )}
          {definition !== null && (
            <>
              <StepDetails
                node={node}
                catalogName={definition.name}
                canSwitchOff={node.id !== graph.entry_node_id && definition.kind !== "control"}
                disabled={readOnly}
                onChange={store.updateNodeDetails}
              />
              <NodeForm
                definition={definition}
                node={node}
                graph={graph}
                catalog={catalogIndex}
                bindings={graph.bindings}
                errors={fieldErrors(problems, node.id)}
                disabled={readOnly}
                updateNodeConfig={store.updateNodeConfig}
                upsertBinding={store.upsertBinding}
                removeBinding={store.removeBinding}
              />
              {node.definition_id !== "loop.item" && !isTrigger(definition) && (
                <div className="border-border border-t pt-5">
                  <PolicySection
                    definition={definition}
                    node={node}
                    disabled={readOnly}
                    updateNodePolicy={store.updateNodePolicy}
                  />
                </div>
              )}
            </>
          )}
        </div>
        <footer className="border-border flex items-center justify-between gap-2 border-t px-6 py-4">
          {readOnly ? (
            <span />
          ) : (
            <Button
              variant="ghost"
              className="text-destructive hover:text-destructive"
              onClick={() => {
                store.applyNodeChanges([{ type: "remove", id: node.id }]);
                close();
              }}
            >
              <Trash2 className="h-4 w-4" />
              {t("nodeEditorDelete")}
            </Button>
          )}
          <Button onClick={close}>{t("nodeEditorDone")}</Button>
        </footer>
      </DialogContent>
    </Dialog>
  );
}
