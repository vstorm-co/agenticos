"use client";

import { FilePlus2, Workflow } from "lucide-react";
import { useTranslations } from "next-intl";

import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui";
import { DIALOG_COLUMN, DIALOG_FORM } from "@/lib/dialog-sizes";
import { cn } from "@/lib/utils";
import { WORKFLOW_TEMPLATES } from "@/lib/workflows/templates";
import type { WorkflowGraph } from "@/lib/workflows/types";

/** What the reader chose: a blank draft (`graph` null) or a template's seed graph. */
export interface WorkflowCreateChoice {
  name: string;
  graph: WorkflowGraph | null;
}

/**
 * The "New workflow" dialog: a blank canvas, or one of the shipped templates.
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
          <button
            type="button"
            disabled={busy}
            onClick={() => onChoose({ name: t("untitledWorkflow"), graph: null })}
            className="hover:border-primary hover:bg-accent flex w-full items-start gap-3 rounded-lg border p-4 text-left transition-colors disabled:opacity-50"
          >
            <FilePlus2 className="text-muted-foreground mt-0.5 size-5 shrink-0" />
            <span className="min-w-0 space-y-1">
              <span className="block font-medium">{t("blankTitle")}</span>
              <span className="text-muted-foreground block text-sm">{t("blankDescription")}</span>
            </span>
          </button>

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
