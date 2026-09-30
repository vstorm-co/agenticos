"use client";

import { useMemo, useState } from "react";
import { MessageSquare, X } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui";
import { validateGraph } from "@/components/workflows/validation";
import { CHAT_TRIGGER } from "@/lib/workflows/triggers";
import type { NodeDefinition } from "@/lib/workflows/types";
import { useWorkflowEditorStore } from "@/stores/workflow-editor-store";

import { ChatPanel } from "./chat-panel";

/**
 * **Open chat** in the header of a draft that starts from a chat message, and
 * the panel it opens. A message runs the draft the way Run does - not while it
 * has problems or an edit is still saving - and each run opens on the canvas.
 */
export function ChatButton({
  workflowId,
  catalog,
  onStarted,
}: {
  workflowId: string;
  catalog: NodeDefinition[];
  onStarted: (runId: string) => void;
}) {
  const t = useTranslations("workflows");
  const tp = useTranslations("pages.workflows");
  const graph = useWorkflowEditorStore((state) => state.graph);
  const isDirty = useWorkflowEditorStore((state) => state.isDirty);
  const [open, setOpen] = useState(false);
  const problems = useMemo(
    () =>
      graph === null ? [] : validateGraph(graph, { items: catalog, total: catalog.length }, t),
    [graph, catalog, t],
  );
  const entry = graph?.nodes.find((node) => node.id === graph.entry_node_id);
  if (entry?.definition_id !== CHAT_TRIGGER) return null;

  const blocked =
    problems.length > 0
      ? tp("runBlockedByProblems", { count: problems.length })
      : isDirty
        ? t("publishSaving")
        : null;

  return (
    <>
      <Button variant="outline" aria-pressed={open} onClick={() => setOpen(!open)}>
        <MessageSquare className="h-4 w-4" />
        {t("chatPanelOpen")}
      </Button>
      {/* Docked beside the canvas rather than over it: each message's run opens
          there, and a modal overlay would hide the very thing being tried. */}
      {open && (
        <aside
          aria-label={t("chatPanelTitle")}
          className="panel-strong fixed inset-y-0 right-0 z-40 flex w-full max-w-md flex-col border-l shadow-lg"
        >
          <div className="flex items-center justify-between border-b p-4">
            <h2 className="font-semibold">{t("chatPanelTitle")}</h2>
            <Button
              variant="ghost"
              size="icon"
              aria-label={t("chatPanelClose")}
              onClick={() => setOpen(false)}
            >
              <X className="size-4" />
            </Button>
          </div>
          <div className="min-h-0 flex-1 p-4">
            <ChatPanel workflowId={workflowId} blocked={blocked} onStarted={onStarted} />
          </div>
        </aside>
      )}
    </>
  );
}
