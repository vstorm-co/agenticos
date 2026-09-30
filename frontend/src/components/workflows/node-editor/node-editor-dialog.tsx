"use client";

import { useMemo, useState } from "react";
import { Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button, Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui";
import { nodeVisual } from "@/components/workflows/node-visuals";
import { NodeForm } from "@/components/workflows/property-panel/node-form";
import { PolicySection } from "@/components/workflows/property-panel/policy-section";
import { StepDetails } from "./step-details";
import { InputPane, OutputPane } from "./step-panes";
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
  /** The workflow being edited: with it, the step's Input and Output show beside its settings. */
  workflowId?: string;
  /**
   * A run's view: the step's Input and Output show what this run's steps handed
   * on - the store's step data - to read, with nothing to test or pin.
   */
  runData?: boolean;
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
 *
 * Editing a workflow, the settings sit between what the step reads and what it
 * hands on, from the last test run or pinned: the data a field is set from is
 * in view while it is set, and **Test step** runs the step alone.
 */
export function NodeEditorDialog({
  workflowId,
  catalog,
  readOnly = false,
  runData = false,
}: NodeEditorDialogProps) {
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

  const [policyShown, setPolicyShown] = useState(false);
  // The fields left since the dialog opened: a value still missing from one of
  // them is said at once, not only once a run or a publish was tried.
  const [left, setLeft] = useState<ReadonlySet<string>>(new Set());
  const close = () => {
    setPolicyShown(false);
    setLeft(new Set());
    store.editNode(null);
  };
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
  const names = nodeNames(graph, catalogIndex);
  const withData = workflowId !== undefined && (runData || !readOnly) && definition !== null;
  const withInput = withData && node.id !== graph.entry_node_id;

  return (
    <Dialog open onOpenChange={(open) => !open && close()}>
      <DialogContent
        className={cn(
          "flex max-h-[88vh] flex-col gap-0 p-0",
          withData ? "h-[88vh] max-w-[min(94vw,1320px)] sm:max-w-[min(94vw,1320px)]" : "max-w-2xl",
        )}
      >
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
                {names.get(node.id) ?? node.definition_id}
              </DialogTitle>
              <WarningBadge count={nodeProblemCount(problems, node.id)} />
            </div>
            <DialogDescription className="text-sm">
              {definition?.description ?? t("panelUnknownDefinition")}
            </DialogDescription>
          </div>
        </header>
        <div
          className={cn(
            "min-h-0 flex-1",
            withData &&
              "grid grid-cols-1 overflow-y-auto lg:overflow-hidden [&>*]:px-6 [&>*]:py-5 lg:[&>*]:overflow-y-auto",
            withInput && "lg:grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)_minmax(0,1fr)]",
            withData && !withInput && "lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]",
          )}
        >
          {withInput && (
            <div className="bg-muted/30 border-border lg:border-r">
              <InputPane
                graph={graph}
                catalog={catalog}
                node={node}
                names={names}
                readOnly={runData}
              />
            </div>
          )}
          <div className={cn("space-y-5", !withData && "h-full overflow-y-auto px-6 py-5")}>
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
                {/* Listens for focus leaving a field inside it; the fields are the
                    controls, this is only where their blur is heard. */}
                {/* eslint-disable-next-line jsx-a11y/no-static-element-interactions */}
                <div
                  onBlur={(event) => {
                    const field = (event.target as HTMLElement)
                      .closest("[data-field]")
                      ?.getAttribute("data-field");
                    if (field != null && !left.has(field)) setLeft(new Set([...left, field]));
                  }}
                >
                  <NodeForm
                    definition={definition}
                    node={node}
                    graph={graph}
                    catalog={catalogIndex}
                    bindings={graph.bindings}
                    errors={fieldErrors(
                      // A value not given yet is said once its field was left, or a
                      // run or a publish was tried; the canvas already marks the step.
                      store.problemsRevealed
                        ? problems
                        : problems.filter(
                            (problem) =>
                              problem.code !== "input-not-bound" ||
                              (problem.field !== null && left.has(problem.field)),
                          ),
                      node.id,
                    )}
                    disabled={readOnly}
                    updateNodeConfig={store.updateNodeConfig}
                    upsertBinding={store.upsertBinding}
                    removeBinding={store.removeBinding}
                  />
                </div>
                {node.definition_id !== "loop.item" && !isTrigger(definition) && (
                  <div className="border-border border-t pt-5">
                    {/* Retries, a time limit and error routing are for later: shown
                      once asked for, or once the step has any of them. */}
                    {policyShown || node.policy ? (
                      <PolicySection
                        definition={definition}
                        node={node}
                        disabled={readOnly}
                        updateNodePolicy={store.updateNodePolicy}
                      />
                    ) : (
                      <button
                        type="button"
                        className="text-muted-foreground hover:text-foreground text-sm"
                        onClick={() => setPolicyShown(true)}
                      >
                        {t("nodeEditorShowPolicy")}
                      </button>
                    )}
                  </div>
                )}
              </>
            )}
          </div>
          {withData && (
            <div className="bg-muted/30 border-border lg:border-l">
              <OutputPane
                readOnly={runData}
                workflowId={workflowId}
                catalog={catalog}
                graph={graph}
                node={node}
                definition={definition}
              />
            </div>
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
