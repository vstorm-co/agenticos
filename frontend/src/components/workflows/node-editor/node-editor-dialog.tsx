"use client";

import Link from "next/link";
import { useMemo, useState } from "react";
import { AlertTriangle, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";

import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogTitle,
  MoreOptions,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui";
import { appToolLabel } from "@/components/workflows/apps";
import { connectionLabel } from "@/lib/mcp-servers";
import { NodeTile } from "@/components/workflows/node-tile";
import { useMcpAppStep } from "@/components/workflows/use-app-connections";
import { ROUTES } from "@/lib/constants";
import { NodeForm } from "@/components/workflows/property-panel/node-form";
import { PolicySection } from "@/components/workflows/property-panel/policy-section";
import { carriesField, scrollNearEdge } from "@/lib/workflows/field-drag";
import { StepName, StepNote, StepSwitch } from "./step-details";
import { InputPane, OutputPane } from "./step-panes";
import {
  fieldErrors,
  nodeNames,
  problemText,
  stepProblems,
} from "@/components/workflows/property-panel/problems";
import {
  AgentTile,
  InlineAgentTile,
  resourcePin,
} from "@/components/workflows/canvas/node-resource";
import { usePanelStore } from "@/components/workflows/property-panel/store-bridge";
import { validateGraph } from "@/components/workflows/validation";
import { DIALOG_CANVAS, DIALOG_COLUMN, DIALOG_FILL, DIALOG_FORM } from "@/lib/dialog-sizes";
import { cn } from "@/lib/utils";
import { isTrigger } from "@/lib/workflows/triggers";
import type { NodeCatalog, NodeDefinition } from "@/lib/workflows/types";
import { MODEL_STEPS, StepEvals } from "./step-evals";

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
  // A model step's evals run the draft, so they are an editor's, as testing is.
  const evaluable = workflowId !== undefined && !readOnly && MODEL_STEPS.has(node.definition_id);
  const pin = resourcePin(node);
  const tile = (
    <NodeTile
      definitionId={node.definition_id}
      category={definition?.category ?? ""}
      className="size-10 rounded-xl"
      iconClassName="size-5"
    />
  );
  const nodeProblems = stepProblems(problems, node.id);
  // Brings a problem's field into view, its message said at once.
  const showField = (field: string) => {
    setTab("parameters");
    setLeft(new Set([...left, field]));
    requestAnimationFrame(() => {
      const target = document.querySelector(`[data-field="${CSS.escape(field)}"]`);
      target?.scrollIntoView?.({ block: "center" });
      // The box a value is typed into, ahead of the Data menu in the label row
      // above it; a field with no box - a picker, a switch - takes its first control.
      const box =
        target?.querySelector<HTMLElement>("textarea, input, [contenteditable='true']") ??
        target?.querySelector<HTMLElement>("button, [tabindex]");
      box?.focus();
    });
  };
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
      {/* Read-only, every setting still shows - disabled, at its value or default -
          as the Parameters tab does, so a reader sees how the step behaves. */}
      {switchable && (
        <StepSwitch node={node} disabled={readOnly} onChange={store.updateNodeDetails} />
      )}
      {withPolicy && (
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
        // A field dragged from the Input pane scrolls the form, or the pane, at
        // their edges: the wheel does nothing while a browser carries a drag.
        onDragOver={(event) => carriesField(event) && scrollNearEdge(event)}
        className={cn(
          "gap-0 p-0 sm:p-0",
          withData ? [DIALOG_CANVAS, DIALOG_FILL] : [DIALOG_FORM, DIALOG_COLUMN],
        )}
      >
        <header className="border-border flex items-start gap-3 border-b px-5 pt-5 pr-14 pb-4 sm:px-6 sm:pr-14">
          {pin?.kind === "agent" ? (
            <AgentTile agentId={pin.id} fallback={tile} className="size-10" />
          ) : pin?.kind === "inline_agent" ? (
            <InlineAgentTile name={pin.name} className="size-10" />
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
            {definition?.id === "mcp.call" && <McpCallNote config={node.config} />}
            {nodeProblems.length > 0 && (
              <div className="pt-2">
                <MoreOptions
                  key={String(store.problemsRevealed)}
                  label={t(store.problemsRevealed ? "stepReviewNeeded" : "stepSetupRemaining", {
                    count: nodeProblems.length,
                  })}
                  defaultOpen={store.problemsRevealed || readOnly}
                >
                  <div className="max-h-28 space-y-2 overflow-y-auto p-1">
                    {nodeProblems.map((problem, index) => {
                      const text = problemText(problem, definition, t);
                      const field = problem.field;
                      return field === null ? (
                        <p
                          key={index}
                          className={cn(
                            "flex items-start gap-2 text-xs",
                            store.problemsRevealed ? "text-destructive" : "text-muted-foreground",
                          )}
                        >
                          <AlertTriangle aria-hidden="true" className="size-3.5 shrink-0" />
                          {text}
                        </p>
                      ) : (
                        <button
                          key={index}
                          type="button"
                          onClick={() => showField(field)}
                          className={cn(
                            "flex items-start gap-2 text-left text-xs hover:underline",
                            store.problemsRevealed ? "text-destructive" : "text-muted-foreground",
                          )}
                        >
                          <AlertTriangle aria-hidden="true" className="size-3.5 shrink-0" />
                          {text}
                        </button>
                      );
                    })}
                  </div>
                </MoreOptions>
              </div>
            )}
          </div>
        </header>
        <div
          className={cn(
            "min-h-0 flex-1 overscroll-contain",
            // The dialog only caps its height here, so `h-full` below it resolves to
            // nothing: the body itself is what scrolls, or a long form runs out of it.
            !withData && "overflow-y-auto",
            withData &&
              "grid grid-cols-1 overflow-y-auto lg:overflow-hidden [&>*]:px-6 [&>*]:py-5 lg:[&>*]:overflow-y-auto",
            withInput &&
              !runData &&
              "lg:grid-cols-[minmax(0,0.85fr)_minmax(0,1.6fr)_minmax(0,0.85fr)]",
            withData && !withInput && !runData && "lg:grid-cols-[minmax(0,1.3fr)_minmax(0,1fr)]",
            // A run's step is read for its data: Input and Output side by side,
            // the settings it ran with folded underneath.
            runData && withInput && "lg:grid-cols-2 lg:grid-rows-[minmax(0,1fr)_auto]",
            runData && !withInput && "lg:grid-rows-[minmax(0,1fr)_auto]",
          )}
        >
          {withInput && (
            <div className="bg-muted/30 border-border min-w-0 lg:border-r">
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
              "order-first min-w-0 space-y-5 lg:order-none",
              !withData && "px-6 py-5",
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
                    {evaluable && <TabsTrigger value="evals">{t("stepTabEvals")}</TabsTrigger>}
                  </TabsList>
                  <TabsContent value="parameters" className="mt-5">
                    {form}
                  </TabsContent>
                  <TabsContent value="settings" className="mt-5">
                    {stepSettings}
                  </TabsContent>
                  {evaluable && workflowId !== undefined && (
                    <TabsContent value="evals" className="mt-5">
                      <StepEvals workflowId={workflowId} graph={graph} node={node} />
                    </TabsContent>
                  )}
                </Tabs>
              ))}
          </div>
          {withData && (
            <div className="bg-muted/30 border-border min-w-0 lg:border-l">
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

/**
 * Says a step on an app's connection is an MCP tool call, on which connection and
 * which tool, with a link to the connection - the friendly name never hides it.
 */
function McpCallNote({ config }: { config: Record<string, unknown> }) {
  const t = useTranslations("workflows");
  const mcp = useMcpAppStep(config);
  if (mcp === null || mcp.tool === "") return null;
  return (
    <p className="text-muted-foreground text-xs">
      {t("appPanelNote", {
        tool: appToolLabel(mcp.app, mcp.tool, t),
        raw: mcp.tool,
        connection: connectionLabel(mcp.connection),
      })}{" "}
      <Link
        href={`${ROUTES.MCP_SERVERS}?server=${encodeURIComponent(mcp.connection.catalog_key ?? "")}`}
        className="underline underline-offset-2"
      >
        {t("appPanelLink")}
      </Link>
    </p>
  );
}
