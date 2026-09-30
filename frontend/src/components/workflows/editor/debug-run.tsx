"use client";

import { useEffect, useRef } from "react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { useWorkflowRun } from "@/hooks";
import { stepDataOf } from "@/lib/workflows/step-data";
import type { NodeDefinition } from "@/lib/workflows/types";
import { useWorkflowEditorStore } from "@/stores/workflow-editor-store";

/**
 * **Debug in editor**: a past run's data, brought into the draft. Every step of
 * the draft that succeeded in that run, outside a loop, gets what it handed on
 * pinned - so a test run starts from where that run was, without calling what it
 * already called - and its Input and Output show the run's data. A deciding step
 * is not pinned: it decides again. Done once, then `onDone` drops the request.
 */
export function DebugRun({
  runId,
  catalog,
  onDone,
}: {
  runId: string;
  catalog: NodeDefinition[];
  onDone: () => void;
}) {
  const t = useTranslations("pages.workflows");
  const { run, nodes } = useWorkflowRun(runId);
  const graph = useWorkflowEditorStore((state) => state.graph);
  const pinOutputs = useWorkflowEditorStore((state) => state.pinOutputs);
  const mergeStepData = useWorkflowEditorStore((state) => state.mergeStepData);
  const done = useRef(false);

  useEffect(() => {
    if (done.current || graph === null || run === null || nodes.length === 0) return;
    done.current = true;
    const kinds = new Map(catalog.map((definition) => [definition.id, definition.kind]));
    const inDraft = new Map(graph.nodes.map((node) => [node.id, node]));
    const pins: Record<string, Record<string, unknown>> = {};
    for (const row of nodes) {
      const node = inDraft.get(row.node_instance_id);
      if (
        node === undefined ||
        row.scope_path.length > 0 ||
        row.output === null ||
        kinds.get(node.definition_id) === "control"
      ) {
        continue;
      }
      pins[node.id] = row.output;
    }
    mergeStepData(stepDataOf(runId, nodes));
    if (Object.keys(pins).length > 0) pinOutputs(pins);
    toast.success(t("runDebugPinned", { count: Object.keys(pins).length }));
    onDone();
  }, [graph, run, nodes, catalog, runId, pinOutputs, mergeStepData, onDone, t]);

  return null;
}
