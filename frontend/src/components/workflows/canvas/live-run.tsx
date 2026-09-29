"use client";

import { type ReactNode, useEffect, useMemo, useRef } from "react";
import Link from "next/link";
import { ExternalLink, X } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui";
import { WorkflowRunStatusBadge } from "@/components/workflows/runs/run-status";
import { useWorkflowRun } from "@/hooks";
import { ROUTES } from "@/lib/constants";
import { useWorkflowEditorStore } from "@/stores/workflow-editor-store";

import { NodeRunOverlayProvider, summarizeNodeRuns } from "./run-overlay";

interface LiveRunProps {
  workflowId: string;
  runId: string;
  onClose: () => void;
  children: ReactNode;
}

/**
 * A test run shown on the canvas as it happens: every step's card takes its
 * status, tries and error from the run, read again every couple of seconds
 * until the run ends, with a bar saying how the run stands.
 *
 * The overlay belongs to the graph that was run. The first edit after it
 * started closes it, since the cards would otherwise describe steps that have
 * since changed.
 */
export function LiveRun({ workflowId, runId, onClose, children }: LiveRunProps) {
  const t = useTranslations("pages.workflows");
  const { run, nodes } = useWorkflowRun(runId);
  const summaries = useMemo(() => summarizeNodeRuns(nodes), [nodes]);
  const graph = useWorkflowEditorStore((state) => state.graph);
  const ran = useRef(graph);

  useEffect(() => {
    if (graph !== ran.current) onClose();
  }, [graph, onClose]);

  const done = nodes.filter((node) => node.status === "succeeded").length;

  return (
    <NodeRunOverlayProvider value={summaries}>
      {children}
      <div
        role="status"
        className="bg-background/95 border-border absolute bottom-4 left-1/2 z-20 flex -translate-x-1/2 items-center gap-3 rounded-xl border px-3 py-2 shadow-md backdrop-blur"
      >
        <span className="text-sm font-medium">{t("liveRunTitle")}</span>
        {run !== null && <WorkflowRunStatusBadge status={run.status} />}
        <span className="text-muted-foreground text-xs tabular-nums">
          {t("liveRunSteps", { count: done })}
        </span>
        <Button asChild size="sm" variant="ghost">
          <Link href={ROUTES.WORKFLOW_RUN_DETAIL(workflowId, runId)}>
            <ExternalLink className="h-4 w-4" />
            {t("liveRunOpen")}
          </Link>
        </Button>
        <Button size="icon" variant="ghost" aria-label={t("liveRunClose")} onClick={onClose}>
          <X className="h-4 w-4" />
        </Button>
      </div>
    </NodeRunOverlayProvider>
  );
}
