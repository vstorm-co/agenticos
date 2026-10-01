"use client";

import { useMemo, useState } from "react";
import { AlertTriangle, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";

import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui";
import { nodeVisual } from "@/components/workflows/node-visuals";
import { NodeForm } from "@/components/workflows/property-panel/node-form";
import { PolicySection } from "@/components/workflows/property-panel/policy-section";
import { StepName, StepNote, StepSwitch } from "./step-details";
import { InputPane, OutputPane } from "./step-panes";
import {
  fieldErrors,
  nodeLevelProblems,
  nodeNames,
} from "@/components/workflows/property-panel/problems";
import { AgentTile, resourcePin } from "@/components/workflows/canvas/node-resource";
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

  const [tab, setTab] = useState("parameters");
  // The fields left since the dialog opened: a value still missing from one of
  // them is said at once, not only once a run or a publish was tried.
  const [left, setLeft] = useState<ReadonlySet<string>>(new Set());
  const close = () => {
    setTab("parameters");
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
  const pin = resourcePin(node);
  const tile = (
    <span
      className={cn(
        "flex size-10 shrink-0 items-center justify-center rounded-xl",
        visual.tileClass,
      )}
    >
      <Icon aria-hidden="true" className="size-5" />
    </span>
  );
  const nodeProblems = nodeLevelProblems(problems, node.id);
  const names = nodeNames(graph, catalogIndex);
  const withData = workflowId !== undefined && (runData || !readOnly) && definition !== null;
  const withInput = withData && node.id !== graph.entry_node_id;

  const form = definition !== null && (
    // Listens for focus leaving a field inside it; the fields are the controls,
    // this is only where their blur is heard.
    // eslint-disable-next-line jsx-a11y/no-static-element-interactions
    <div
      onBlur={(event) => {
        // Focus moving into a field's own list - a picker opening - has not left it.
        const into = event.relatedTarget as HTMLElement | null;
        if (into?.closest("[data-radix-popper-content-wrapper]")) return;
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
          // A value not given yet is said once its field was left, or a run or
          // a publish was tried; the canvas already marks the step.
          store.problemsRevealed
            ? problems
            : problems.filter(
                (problem) =>
                  (problem.code !== "input-not-bound" && problem.code !== "config-not-set") ||
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
  );
  // How the step runs rather than what it does - n8n's Settings tab: whether it
  // runs at all, what happens when it is slow or fails, and a note.
  const switchable =
    definition !== null && node.id !== graph.entry_node_id && definition.kind !== "control";
  const withPolicy =
    definition !== null && node.definition_id !== "loop.item" && !isTrigger(definition);
  const customised = node.disabled === true || node.policy != null || Boolean(node.notes);
  const stepSettings = definition !== null && (
    <div className="space-y-6">
      {switchable && !readOnly && <StepSwitch node={node} onChange={store.updateNodeDetails} />}
      {withPolicy && (!readOnly || node.policy) && (
        <PolicySection
          definition={definition}
          node={node}
          disabled={readOnly}
          updateNodePolicy={store.updateNodePolicy}
        />
      )}
      <StepNote node={node} disabled={readOnly} onChange={store.updateNodeDetails} />
    </div>
  );

  return (
    <Dialog open onOpenChange={(open) => !open && close()}>
      <DialogContent
        className={cn(
          "flex max-h-[88vh] flex-col gap-0 p-0",
          withData ? "h-[88vh] max-w-[min(94vw,1320px)] sm:max-w-[min(94vw,1320px)]" : "max-w-2xl",
        )}
      >
        <header className="border-border flex items-start gap-3 border-b px-6 pt-6 pr-14 pb-4">
          {pin?.kind === "agent" ? (
            <AgentTile agentId={pin.id} fallback={tile} className="size-10" />
          ) : (
            tile
          )}
          <div className="min-w-0 flex-1 space-y-1">
            <div className="flex items-center gap-2">
              <DialogTitle className="truncate text-base">
                {definition === null ? (
                  (names.get(node.id) ?? node.definition_id)
                ) : (
                  <StepName
                    node={node}
                    name={names.get(node.id) ?? definition.name}
                    catalogName={definition.name}
                    disabled={readOnly}
                    onChange={store.updateNodeDetails}
                  />
                )}
              </DialogTitle>
            </div>
            <DialogDescription className="text-sm">
              {definition === null
                ? t("panelUnknownDefinition")
                : // A step with a name of its own still says what kind of step it is.
                  node.label
                  ? `${definition.name} · ${definition.description}`
                  : definition.description}
            </DialogDescription>
            {nodeProblems.map((problem, index) => (
              <p key={index} className="text-destructive flex items-center gap-1.5 text-xs">
                <AlertTriangle aria-hidden="true" className="size-3.5 shrink-0" />
                {problem.message}
              </p>
            ))}
          </div>
        </header>
        <div
          className={cn(
            "min-h-0 flex-1",
            withData &&
              "grid grid-cols-1 overflow-y-auto lg:overflow-hidden [&>*]:px-6 [&>*]:py-5 lg:[&>*]:overflow-y-auto",
            withInput && !runData && "lg:grid-cols-[minmax(0,1fr)_minmax(0,1.3fr)_minmax(0,1fr)]",
            withData && !withInput && !runData && "lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]",
            // A run's step is read for its data: Input and Output side by side,
            // the settings it ran with folded underneath.
            runData && withInput && "lg:grid-cols-2 lg:grid-rows-[minmax(0,1fr)_auto]",
            runData && !withInput && "lg:grid-rows-[minmax(0,1fr)_auto]",
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
          <div
            className={cn(
              "space-y-5",
              !withData && "h-full overflow-y-auto px-6 py-5",
              runData && "border-border lg:order-last lg:col-span-2 lg:border-t",
            )}
          >
            {definition !== null &&
              (runData ? (
                // A run's step is looked at for what it did: its settings are
                // there to check, not the first thing in the way.
                <details className="group">
                  <summary className="text-muted-foreground hover:text-foreground cursor-pointer text-sm select-none">
                    {t("nodeEditorRanWith")}
                  </summary>
                  <div className="mt-4">{form}</div>
                </details>
              ) : (
                <Tabs value={tab} onValueChange={setTab}>
                  <TabsList>
                    <TabsTrigger value="parameters">{t("stepTabParameters")}</TabsTrigger>
                    <TabsTrigger value="settings">
                      {t("stepTabSettings")}
                      {customised && (
                        <span
                          aria-label={t("stepTabSettingsSet")}
                          className="bg-foreground/60 size-1.5 rounded-full"
                        />
                      )}
                    </TabsTrigger>
                  </TabsList>
                  <TabsContent value="parameters" className="mt-5">
                    {form}
                  </TabsContent>
                  <TabsContent value="settings" className="mt-5">
                    {stepSettings}
                  </TabsContent>
                </Tabs>
              ))}
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
