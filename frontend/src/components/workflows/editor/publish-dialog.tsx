"use client";

import { useMemo, useState } from "react";
import { UploadCloud } from "lucide-react";
import { useTranslations } from "next-intl";

import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
  Label,
  Textarea,
} from "@/components/ui";
import { ProblemsFooter } from "@/components/workflows/property-panel/problems";
import type { ValidationProblem } from "@/components/workflows/validation";
import { validateGraph } from "@/components/workflows/validation";
import { ApiError, fieldProblems } from "@/lib/api-error";
import { DIALOG_FORM, DIALOG_SCROLL } from "@/lib/dialog-sizes";
import { cn } from "@/lib/utils";
import type {
  NodeCatalog,
  NodeDefinition,
  Uuid,
  WorkflowPublish,
  WorkflowVersionRead,
} from "@/lib/workflows/types";
import { useWorkflowEditorStore } from "@/stores/workflow-editor-store";

/**
 * Turn a server field problem into the panel's problem shape.
 *
 * `GraphValidationError` scopes each problem to `nodes.<id>`, `edges.<id>` or
 * `bindings.<index>`; the first two map to a node- or edge-scoped problem the
 * panel already knows how to show, and anything else is graph-level.
 */
function toValidationProblem(field: string, message: string): ValidationProblem {
  const separator = field.indexOf(".");
  const scope = separator === -1 ? field : field.slice(0, separator);
  const ref = separator === -1 ? "" : field.slice(separator + 1);
  if (scope === "nodes") return { nodeId: ref, edgeId: null, field: null, code: "server", message };
  if (scope === "edges") return { nodeId: null, edgeId: ref, field: null, code: "server", message };
  return { nodeId: null, edgeId: null, field: null, code: "server", message };
}

interface PublishDialogProps {
  /** The node catalog, for the client-side validation mirror. */
  catalog: NodeDefinition[];
  /** `useWorkflow(id).publish.mutateAsync`. */
  publish: (input: WorkflowPublish) => Promise<WorkflowVersionRead>;
}

/**
 * The publish control.
 *
 * Publishing freezes the current draft as an immutable version. The client-side
 * validation mirror runs first and the confirm is blocked while any problem
 * stands, so an obviously invalid graph never reaches the server. A server
 * refusal — a rule the mirror does not carry, a resource that went away — comes
 * back scoped to a node or edge and is shown through the same problems display
 * the property panel uses; clicking one selects it on the canvas.
 */
export function PublishDialog({ catalog, publish }: PublishDialogProps) {
  const t = useTranslations("workflows");
  const graph = useWorkflowEditorStore((state) => state.graph);
  const expectedRevision = useWorkflowEditorStore((state) => state.expectedRevision);
  const setSelection = useWorkflowEditorStore((state) => state.setSelection);
  const setConflict = useWorkflowEditorStore((state) => state.setConflict);

  const [open, setOpen] = useState(false);
  const [note, setNote] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [serverProblems, setServerProblems] = useState<ValidationProblem[]>([]);

  const nodeCatalog: NodeCatalog = useMemo(
    () => ({ items: catalog, total: catalog.length }),
    [catalog],
  );

  const clientProblems = useMemo(
    () => (graph === null ? [] : validateGraph(graph, nodeCatalog, t)),
    [graph, nodeCatalog, t],
  );

  const blocked = clientProblems.length > 0;
  const problems = clientProblems.length > 0 ? clientProblems : serverProblems;

  const selectNode = (nodeId: Uuid) => {
    setSelection({ nodeIds: [nodeId], edgeIds: [] });
    setOpen(false);
  };

  const confirm = async () => {
    if (expectedRevision === null) return;
    setSubmitting(true);
    setServerProblems([]);
    try {
      await publish({ note: note.trim() || null, expected_revision: expectedRevision });
      setOpen(false);
      setNote("");
    } catch (error) {
      // A `REVISION_CONFLICT` (`409`) means the draft moved on since this editor
      // read it — publishing into a stale revision. It carries the current
      // revision but no field problems, so it would otherwise vanish. Hand it to
      // the shared conflict banner (Overwrite / Reload) and close the dialog.
      if (error instanceof ApiError && error.status === 409) {
        const current = error.details?.current_revision;
        if (typeof current === "number") {
          setConflict(current);
          setOpen(false);
          return;
        }
      }
      setServerProblems(
        fieldProblems(error).map((problem) => toValidationProblem(problem.field, problem.message)),
      );
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button size="sm">
          <UploadCloud className="h-4 w-4" aria-hidden />
          {t("publish")}
        </Button>
      </DialogTrigger>
      <DialogContent className={cn(DIALOG_FORM, DIALOG_SCROLL)}>
        <DialogHeader>
          <DialogTitle>{t("publishTitle")}</DialogTitle>
          <DialogDescription>{t("publishDescription")}</DialogDescription>
        </DialogHeader>

        <div className="space-y-2">
          <Label htmlFor="workflow-publish-note">{t("publishNoteLabel")}</Label>
          <Textarea
            id="workflow-publish-note"
            value={note}
            onChange={(event) => setNote(event.target.value)}
            placeholder={t("publishNotePlaceholder")}
            rows={3}
          />
        </div>

        {clientProblems.length > 0 && (
          <p className="text-muted-foreground text-xs">{t("publishBlocked")}</p>
        )}
        <ProblemsFooter problems={problems} onSelectNode={selectNode} />

        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)} disabled={submitting}>
            {t("publishCancel")}
          </Button>
          <Button onClick={() => void confirm()} disabled={blocked || submitting}>
            {t("publishConfirm")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
