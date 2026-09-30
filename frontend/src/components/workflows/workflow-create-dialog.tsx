"use client";

import { Workflow } from "lucide-react";
import { useTranslations } from "next-intl";

import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui";
import { nodeVisual } from "@/components/workflows/node-visuals";
import { DIALOG_COLUMN, DIALOG_FORM } from "@/lib/dialog-sizes";
import { cn } from "@/lib/utils";
import { WORKFLOW_TEMPLATES } from "@/lib/workflows/templates";
import {
  API_TRIGGER,
  CHAT_TRIGGER,
  MANUAL_TRIGGER,
  SCHEDULE_TRIGGER,
  TABLE_RECORD_TRIGGER,
  TRIGGER_CATEGORY,
  WEBHOOK_TRIGGER,
  WORKFLOW_FAILED_TRIGGER,
} from "@/lib/workflows/triggers";
import type { WorkflowGraph } from "@/lib/workflows/types";

/** The ways a new workflow can start, in the order a builder reaches for them. */
const STARTS = [
  { id: MANUAL_TRIGGER, key: "manual" },
  { id: API_TRIGGER, key: "api" },
  { id: CHAT_TRIGGER, key: "chat" },
  { id: WEBHOOK_TRIGGER, key: "webhook" },
  { id: SCHEDULE_TRIGGER, key: "schedule" },
  { id: TABLE_RECORD_TRIGGER, key: "tableRecord" },
  { id: WORKFLOW_FAILED_TRIGGER, key: "workflowFailed" },
] as const;

/** A draft of one trigger node - where every new workflow begins. */
export function startingGraph(definitionId: string): WorkflowGraph {
  const id = crypto.randomUUID();
  return {
    entry_node_id: id,
    nodes: [
      {
        id,
        definition_id: definitionId,
        definition_version: 1,
        config: {},
        layout: { x: 0, y: 0 },
      },
    ],
    edges: [],
    bindings: [],
    scopes: [],
  };
}

/** What the reader chose: a blank draft (`graph` null) or a template's seed graph. */
export interface WorkflowCreateChoice {
  name: string;
  graph: WorkflowGraph | null;
}

/**
 * The "New workflow" dialog: how it starts - one trigger, on an otherwise empty
 * canvas - or one of the shipped templates.
 *
 * It holds no state and does no fetching — it hands the caller a
 * {@link WorkflowCreateChoice} and the page's `create` mutation does the rest,
 * routing into the editor on success. Templates are static (`WORKFLOW_TEMPLATES`);
 * their name and description are catalog copy keyed on the template id.
 */
export function WorkflowCreateDialog({
  open,
  onOpenChange,
  onChoose,
  busy,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onChoose: (choice: WorkflowCreateChoice) => void;
  busy: boolean;
}) {
  const t = useTranslations("pages.workflows");

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className={cn(DIALOG_COLUMN, DIALOG_FORM)}>
        <DialogHeader>
          <DialogTitle>{t("createDialogTitle")}</DialogTitle>
          <DialogDescription>{t("createDialogDescription")}</DialogDescription>
        </DialogHeader>

        <div className="min-h-0 flex-1 space-y-3 overflow-y-auto p-1">
          <p className="text-muted-foreground text-xs font-medium tracking-wide uppercase">
            {t("startHeading")}
          </p>
          <div className="grid gap-2 sm:grid-cols-2">
            {STARTS.map((start) => {
              const visual = nodeVisual(start.id, TRIGGER_CATEGORY);
              const Icon = visual.icon;
              return (
                <button
                  key={start.id}
                  type="button"
                  disabled={busy}
                  onClick={() =>
                    onChoose({ name: t("untitledWorkflow"), graph: startingGraph(start.id) })
                  }
                  className="hover:border-foreground/30 hover:bg-accent flex w-full items-start gap-3 rounded-lg border p-3 text-left transition-colors disabled:opacity-50"
                >
                  <span
                    className={cn(
                      "flex size-8 shrink-0 items-center justify-center rounded-lg",
                      visual.tileClass,
                    )}
                  >
                    <Icon aria-hidden="true" className="size-4" />
                  </span>
                  <span className="min-w-0 space-y-0.5">
                    <span className="block text-sm font-medium">
                      {t(`start.${start.key}.name`)}
                    </span>
                    <span className="text-muted-foreground block text-xs">
                      {t(`start.${start.key}.description`)}
                    </span>
                  </span>
                </button>
              );
            })}
          </div>

          <p className="text-muted-foreground pt-2 text-xs font-medium tracking-wide uppercase">
            {t("templatesHeading")}
          </p>

          {WORKFLOW_TEMPLATES.map((template) => (
            <div
              key={template.id}
              className="flex items-start justify-between gap-4 rounded-lg border p-4"
            >
              <div className="min-w-0 space-y-1">
                <div className="flex items-center gap-2">
                  <Workflow className="text-muted-foreground size-4 shrink-0" />
                  <span className="font-medium">{t(`templates.${template.id}.name`)}</span>
                </div>
                <p className="text-muted-foreground text-sm">
                  {t(`templates.${template.id}.description`)}
                </p>
              </div>
              <Button
                variant="outline"
                size="sm"
                className="shrink-0"
                disabled={busy}
                onClick={() =>
                  onChoose({ name: t(`templates.${template.id}.name`), graph: template.graph })
                }
              >
                {t("useTemplate")}
              </Button>
            </div>
          ))}
        </div>
      </DialogContent>
    </Dialog>
  );
}
