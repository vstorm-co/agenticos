"use client";

import { useMemo, useState } from "react";
import { AlertTriangle, CheckCircle2, Plus, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button, Popover, PopoverContent, PopoverTrigger } from "@/components/ui";
import { isAddableInScope } from "@/components/workflows/palette/scope";
import { NodePicker } from "@/components/workflows/picker";
import { ProblemsFooter, nodeNames } from "@/components/workflows/property-panel/problems";
import type { ValidationProblem } from "@/components/workflows/validation";
import type { NodeDefinition, Uuid } from "@/lib/workflows/types";
import { useWorkflowEditorStore } from "@/stores/workflow-editor-store";

import { ScopeBreadcrumb } from "./scope-breadcrumb";

interface CanvasToolbarProps {
  catalog: NodeDefinition[];
  problems: readonly ValidationProblem[];
  readOnly: boolean;
  /** Whether the graph in view has no steps - the picker then opens from its middle. */
  empty: boolean;
  onAdd: (definition: NodeDefinition) => void;
}

/**
 * What floats over the canvas: a quiet "+" for adding a step and the loop being
 * viewed on the left, whether the draft can be published on the right, and -
 * while several steps are selected - what can be done to all of them. An empty
 * canvas offers **Add step** in its middle instead.
 *
 * The canvas has the editor's whole width, so these stay small and out of the
 * graph's way; the step picker and the problem list open from them rather than
 * sitting beside the graph.
 */
export function CanvasToolbar({ catalog, problems, readOnly, empty, onAdd }: CanvasToolbarProps) {
  const t = useTranslations("workflows");
  const graph = useWorkflowEditorStore((state) => state.graph);
  const scopePath = useWorkflowEditorStore((state) => state.scopePath);
  const selection = useWorkflowEditorStore((state) => state.selection);
  const applyNodeChanges = useWorkflowEditorStore((state) => state.applyNodeChanges);
  const focusNode = useWorkflowEditorStore((state) => state.focusNode);
  const editNode = useWorkflowEditorStore((state) => state.editNode);
  const [adding, setAdding] = useState(false);
  const [listing, setListing] = useState(false);

  const offered = useMemo(
    () => catalog.filter((definition) => isAddableInScope(definition, scopePath)),
    [catalog, scopePath],
  );
  const names = useMemo(
    () => nodeNames(graph, { items: catalog, total: catalog.length }),
    [graph, catalog],
  );
  const selected = selection.nodeIds;
  const [startOpen, setStartOpen] = useState(false);

  const pickerFor = (close: () => void) => (
    <PopoverContent
      align="start"
      sideOffset={8}
      className="w-[22rem] p-0"
      onCloseAutoFocus={(event) => event.preventDefault()}
    >
      <NodePicker
        offered={offered}
        draggable
        onPick={(definition) => {
          close();
          onAdd(definition);
        }}
      />
    </PopoverContent>
  );
  const picker = pickerFor(() => setAdding(false));

  return (
    <>
      <div className="pointer-events-none absolute inset-x-3 top-3 z-10 flex items-start justify-between gap-3">
        <div className="pointer-events-auto flex flex-wrap items-center gap-2">
          {!readOnly && !empty && (
            <Popover open={adding} onOpenChange={setAdding}>
              <PopoverTrigger asChild>
                <Button
                  size="icon"
                  variant="outline"
                  aria-label={t("toolbarAddStep")}
                  title={t("toolbarAddStep")}
                  className="bg-background/70 hover:bg-background size-8 rounded-lg shadow-sm backdrop-blur"
                >
                  <Plus className="h-4 w-4" />
                </Button>
              </PopoverTrigger>
              {picker}
            </Popover>
          )}
          <ScopeBreadcrumb catalog={catalog} />
        </div>
        {!readOnly && graph !== null && graph.nodes.length > 0 && (
          <div className="pointer-events-auto">
            {problems.length === 0 ? (
              <span className="bg-background/90 border-border text-muted-foreground flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs shadow-sm backdrop-blur">
                <CheckCircle2 aria-hidden="true" className="size-3.5 text-emerald-600" />
                {t("toolbarReady")}
              </span>
            ) : (
              <Popover open={listing} onOpenChange={setListing}>
                <PopoverTrigger asChild>
                  <button
                    type="button"
                    className="bg-background/90 border-border text-destructive hover:bg-accent flex items-center gap-1.5 rounded-lg border px-3 py-1.5 text-xs font-medium shadow-sm backdrop-blur"
                  >
                    <AlertTriangle aria-hidden="true" className="size-3.5" />
                    {t("panelProblemsCount", { count: problems.length })}
                  </button>
                </PopoverTrigger>
                <PopoverContent align="end" sideOffset={8} className="w-96 p-3">
                  <p className="text-muted-foreground mb-2 text-xs">{t("toolbarProblemsHint")}</p>
                  <ProblemsFooter
                    problems={problems}
                    names={names}
                    defaultOpen
                    onSelectNode={(nodeId: Uuid) => {
                      setListing(false);
                      focusNode(nodeId);
                      editNode(nodeId);
                    }}
                  />
                </PopoverContent>
              </Popover>
            )}
          </div>
        )}
      </div>
      {empty && (
        <div className="pointer-events-none absolute inset-0 z-10 flex flex-col items-center justify-center gap-3 p-4 text-center">
          {!readOnly && (
            <Popover open={startOpen} onOpenChange={setStartOpen}>
              <PopoverTrigger asChild>
                <Button className="pointer-events-auto shadow-sm">
                  <Plus className="h-4 w-4" />
                  {t("toolbarAddStep")}
                </Button>
              </PopoverTrigger>
              {pickerFor(() => setStartOpen(false))}
            </Popover>
          )}
          <p className="text-muted-foreground text-sm">{t("canvasHint")}</p>
        </div>
      )}
      {!readOnly && selected.length > 1 && (
        <div className="bg-background/95 border-border absolute bottom-4 left-1/2 z-10 flex -translate-x-1/2 items-center gap-3 rounded-xl border px-3 py-2 shadow-md backdrop-blur">
          <span className="text-sm">{t("panelMultiSelected", { count: selected.length })}</span>
          <Button
            size="sm"
            variant="ghost"
            className="text-destructive hover:text-destructive"
            onClick={() => applyNodeChanges(selected.map((id) => ({ type: "remove", id })))}
          >
            <Trash2 className="h-4 w-4" />
            {t("panelBulkDelete")}
          </Button>
        </div>
      )}
    </>
  );
}
