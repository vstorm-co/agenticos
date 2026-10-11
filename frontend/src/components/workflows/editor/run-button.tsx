"use client";

import { useEffect, useMemo, useState } from "react";
import { Play } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui";
import { StartRunDialog } from "@/components/workflows/runs/start-run-dialog";
import { validateGraph } from "@/components/workflows/validation";
import { useWorkflowRuns } from "@/hooks";
import { declaredFields, sampleRunInput } from "@/lib/workflows/triggers";
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
  const t = useTranslations("pages.workflows");
  const tw = useTranslations("workflows");
  const graph = useWorkflowEditorStore((state) => state.graph);
  const isDirty = useWorkflowEditorStore((state) => state.isDirty);
  const revealProblems = useWorkflowEditorStore((state) => state.revealProblems);
  const watchRun = useWorkflowEditorStore((state) => state.watchRun);
  const { start } = useWorkflowRuns(workflowId);
  const [asking, setAsking] = useState(false);

  const problems = useMemo(
    () =>
      graph === null ? [] : validateGraph(graph, { items: catalog, total: catalog.length }, tw),
    [graph, catalog, tw],
  );
  const fields = declaredFields(graph);
  const empty = graph === null || graph.nodes.length === 0;
  const blocked = empty || problems.length > 0 || isDirty || start.isPending;

  const begin = (input: Record<string, unknown>) =>
    start.mutate(
      { workflow_id: workflowId, mode: "test", input },
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
    if (fields.length > 0) setAsking(true);
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
        <Play className="h-4 w-4" />
        {t("runDraft")}
      </Button>
      {asking && (
        <StartRunDialog
          open
          onOpenChange={setAsking}
          canRunLive={false}
          canTest
          busy={start.isPending}
          testFields={fields}
          onStart={({ input }) => begin(input)}
        />
      )}
    </>
  );
}
