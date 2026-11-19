"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { ChatPanel } from "./chat-panel";
import { Sheet, SheetContent, SheetHeader, SheetTitle, SheetClose } from "@/components/ui";
import { Pin, Play } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button, Popover, PopoverContent, PopoverTrigger } from "@/components/ui";
import { StartRunDialog } from "@/components/workflows/runs/start-run-dialog";
import { validateGraph, withTableDrift } from "@/components/workflows/validation";
import { useWorkflowRuns } from "@/hooks";
import {
  declaredFields,
  declaredInputSchema,
  sampleRunInput,
  entryNodes,
  entryGraph,
  FORM_TRIGGER,
  CHAT_TRIGGER,
} from "@/lib/workflows/triggers";
import type { NodeDefinition } from "@/lib/workflows/types";
import { useWorkflowEditorStore } from "@/stores/workflow-editor-store";

interface RunButtonProps {
  workflowId: string;
  catalog: NodeDefinition[];
  /** A test run was admitted: the editor shows it on the canvas. */
  onStarted: (runId: string) => void;
}

/**
 * **Run** - a test run of the draft, from the editor, the way a builder tries
 * what they just built. `Ctrl`/`Cmd` + `Enter` does the same.
 *
 * A draft with declared input fields asks for them first; any other starts at
 * once, with the input its trigger would hand on. It waits while an edit is
 * still saving - the run executes the saved draft - and says why it cannot run
 * while the draft has problems.
 */
export function RunButton({ workflowId, catalog, onStarted }: RunButtonProps) {
  const router = useRouter();
  const [chatOpen, setChatOpen] = useState(false);
  const t = useTranslations("pages.workflows");
  const tw = useTranslations("workflows");
  const graph = useWorkflowEditorStore((state) => state.graph);
  const isDirty = useWorkflowEditorStore((state) => state.isDirty);
  const revealProblems = useWorkflowEditorStore((state) => state.revealProblems);
  const watchRun = useWorkflowEditorStore((state) => state.watchRun);
  const tableDrift = useWorkflowEditorStore((state) => state.tableDrift);
  const [asking, setAsking] = useState(false);
  const { start } = useWorkflowRuns(workflowId, asking);

  const problems = useMemo(
    () =>
      graph === null
        ? []
        : withTableDrift(
            validateGraph(graph, { items: catalog, total: catalog.length }, tw),
            tableDrift,
            tw,
          ),
    [graph, catalog, tw, tableDrift],
  );
  const fields = declaredFields(graph);
  const inputSchema = declaredInputSchema(graph);
  const entries =
    graph === null
      ? []
      : entryNodes(graph).map((node) => {
          const branch = entryGraph(graph, node.id);
          return {
            id: node.id,
            name:
              node.label ??
              catalog.find((definition) => definition.id === node.definition_id)?.name ??
              node.definition_id,
            fields: declaredFields(branch),
            inputSchema: declaredInputSchema(branch),
            sample: sampleRunInput(branch),
          };
        });
  // Steps with pinned test data hand on that data instead of running: the
  // builder should know before starting a test run which ones will.
  const pinnedSteps =
    graph?.nodes
      .filter((node) => !node.disabled && node.pinned_output != null)
      .map(
        (node) =>
          node.label ??
          catalog.find((definition) => definition.id === node.definition_id)?.name ??
          node.definition_id,
      ) ?? [];
  const empty = graph === null || graph.nodes.length === 0;
  const blocked = empty || problems.length > 0 || isDirty || start.isPending;

  const begin = (input: Record<string, unknown>, entry_node_id?: string) =>
    start.mutate(
      { workflow_id: workflowId, mode: "test", input, ...(entry_node_id ? { entry_node_id } : {}) },
      {
        onSuccess: (run) => {
          setAsking(false);
          watchRun(run.id);
          onStarted(run.id);
        },
      },
    );
  const run = () => {
    revealProblems();
    if (blocked) return;
    const entry = graph?.nodes.find((node) => node.id === graph.entry_node_id);
    if (entries.length === 1 && entry?.definition_id === FORM_TRIGGER) {
      router.push(`/workflows/${workflowId}/form-preview?entry=${encodeURIComponent(entry.id)}`);
      return;
    }
    if (entries.length === 1 && entry?.definition_id === CHAT_TRIGGER) {
      setChatOpen(true);
      return;
    }
    if (fields.length > 0 || inputSchema !== null || entries.length > 1) setAsking(true);
    else begin(sampleRunInput(graph));
  };

  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      // A field that answers Ctrl+Enter itself - saving what was typed in it -
      // has taken the key.
      if (event.key === "Enter" && (event.metaKey || event.ctrlKey) && !event.defaultPrevented) {
        event.preventDefault();
        run();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  });

  const reason = empty
    ? t("runNeedsSteps")
    : problems.length > 0
      ? t("runBlockedByProblems", { count: problems.length })
      : isDirty
        ? tw("publishSaving")
        : t("runHint");

  return (
    <>
      <Button variant="outline" onClick={run} disabled={blocked} title={reason}>
        <Play aria-hidden="true" className="h-4 w-4" />
        {t("runDraft")}
      </Button>
      {pinnedSteps.length > 0 && (
        <Popover>
          <PopoverTrigger asChild>
            <Button
              type="button"
              variant="ghost"
              className="text-muted-foreground h-8 gap-1.5 px-2 text-xs tabular-nums"
              aria-label={t("runPinnedCount", { count: pinnedSteps.length })}
              data-pinned-steps
            >
              <Pin aria-hidden="true" className="size-3.5" />
              <span aria-hidden="true">{pinnedSteps.length}</span>
            </Button>
          </PopoverTrigger>
          <PopoverContent align="end" className="w-72 space-y-1.5 text-sm">
            <p className="font-medium">{t("runPinnedCount", { count: pinnedSteps.length })}</p>
            <p className="text-muted-foreground">
              {t("runPinnedHint", { steps: pinnedSteps.join(", ") })}
            </p>
          </PopoverContent>
        </Popover>
      )}
      <Sheet open={chatOpen} onOpenChange={setChatOpen}>
        <SheetContent side="right" className="flex w-full flex-col sm:max-w-xl">
          <SheetHeader>
            <SheetTitle>{tw("chatPanelTitle")}</SheetTitle>
            <SheetClose onClick={() => setChatOpen(false)} />
          </SheetHeader>
          <div className="min-h-0 flex-1 p-4">
            <ChatPanel
              workflowId={workflowId}
              blocked={blocked ? reason : null}
              onStarted={onStarted}
            />
          </div>
        </SheetContent>
      </Sheet>
      {asking && (
        <StartRunDialog
          open
          onOpenChange={setAsking}
          canRunLive={false}
          canTest
          busy={start.isPending}
          error={start.error}
          onInputChange={start.reset}
          testFields={fields}
          testInputSchema={inputSchema}
          sampleInput={sampleRunInput(graph)}
          entries={entries.length > 1 ? entries : []}
          onStart={({ input, entry_node_id }) => begin(input, entry_node_id)}
        />
      )}
    </>
  );
}
