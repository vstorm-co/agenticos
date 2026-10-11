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
import { nodeNames, ProblemsFooter } from "@/components/workflows/property-panel/problems";
import type { ValidationProblem } from "@/components/workflows/validation";
import { validateGraph } from "@/components/workflows/validation";
import { ApiError, fieldProblems } from "@/lib/api-error";
import { DIALOG_FORM, DIALOG_SCROLL } from "@/lib/dialog-sizes";
import { cn } from "@/lib/utils";
import type {
  NodeCatalog,
  NodeDefinition,
  Uuid,
  WorkflowDetail,
  WorkflowPublish,
  WorkflowPublished,
} from "@/lib/workflows/types";
import { useWorkflowVersions } from "@/hooks";
import { WebhookSecretDialog } from "@/components/workflows/triggers";
import { triggerNodeOf } from "@/lib/workflows/triggers";
import { resolveDefinitions } from "@/components/workflows/validation/topology";
import { useWorkflowEditorStore } from "@/stores/workflow-editor-store";

import { useLiveChanges } from "./workflow-status";

/**
 * Turn a server field problem into the panel's problem shape.
 *
 * `GraphValidationError` scopes each problem to `nodes.<id>`, `edges.<id>` or
 * `bindings.<index>` - a node's own field after its id, as in
 * `nodes.<id>.config.table`; the first two map to a node- or edge-scoped problem
 * the panel already knows how to show, and anything else is graph-level.
 */
function toValidationProblem(field: string, message: string): ValidationProblem {
  const [scope = "", ref = ""] = field.split(".");
  if (scope === "nodes") return { nodeId: ref, edgeId: null, field: null, code: "server", message };
  if (scope === "edges") return { nodeId: null, edgeId: ref, field: null, code: "server", message };
  return { nodeId: null, edgeId: null, field: null, code: "server", message };
}

interface PublishDialogProps {
  /** The workflow being published: which version it makes, and what it changes. */
  workflow: WorkflowDetail;
  /** The node catalog, for the client-side validation mirror. */
  catalog: NodeDefinition[];
  /** `useWorkflow(id).publish.mutateAsync`. */
  publish: (input: WorkflowPublish) => Promise<WorkflowPublished>;
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
 *
 * Publishing is also what switches the draft's trigger on, so the dialog names
 * it; a webhook switched on for the first time comes back with its signing
 * secret, shown here once in the dialog the Trigger sheet's rotate uses.
 */
export function PublishDialog({ workflow, catalog, publish }: PublishDialogProps) {
  const t = useTranslations("workflows");
  const graph = useWorkflowEditorStore((state) => state.graph);
  const { live, changed } = useLiveChanges(workflow, graph);
  // Newest first: a publish makes the one after it, whichever version is live.
  const { versions } = useWorkflowVersions(workflow.id);
  const next = (versions[0]?.version ?? 0) + 1;
  const expectedRevision = useWorkflowEditorStore((state) => state.expectedRevision);
  const isDirty = useWorkflowEditorStore((state) => state.isDirty);
  const focusNode = useWorkflowEditorStore((state) => state.focusNode);
  const setConflict = useWorkflowEditorStore((state) => state.setConflict);
  const revealProblems = useWorkflowEditorStore((state) => state.revealProblems);

  const [open, setOpen] = useState(false);
  const [note, setNote] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [serverProblems, setServerProblems] = useState<ValidationProblem[]>([]);
  const [webhook, setWebhook] = useState<{ url: string; secret: string } | null>(null);

  const nodeCatalog: NodeCatalog = useMemo(
    () => ({ items: catalog, total: catalog.length }),
    [catalog],
  );

  const clientProblems = useMemo(
    () => (graph === null ? [] : validateGraph(graph, nodeCatalog, t)),
    [graph, nodeCatalog, t],
  );

  const trigger = useMemo(() => {
    if (graph === null) return null;
    const node = triggerNodeOf(graph, resolveDefinitions(graph, nodeCatalog));
    return node === null
      ? null
      : (catalog.find((definition) => definition.id === node.definition_id)?.name ?? null);
  }, [graph, nodeCatalog, catalog]);

  const blocked = clientProblems.length > 0;
  const problems = clientProblems.length > 0 ? clientProblems : serverProblems;

  const selectNode = (nodeId: Uuid) => {
    focusNode(nodeId);
    setOpen(false);
  };

  const confirm = async () => {
    // Publishing freezes the server's stored draft. While `isDirty` stands, the
    // canvas holds edits the last PATCH has not persisted (an autosave still in
    // its debounce or in flight), so the server draft is older than what the user
    // sees. `markSaved` clears `isDirty` only after a successful save, so
    // `!isDirty` guarantees the stored draft equals the current canvas.
    if (expectedRevision === null || isDirty) return;
    setSubmitting(true);
    setServerProblems([]);
    try {
      const published = await publish({
        note: note.trim() || null,
        expected_revision: expectedRevision,
      });
      setOpen(false);
      setNote("");
      const url = published.exposure?.webhook_url;
      if (published.webhook_secret && url) setWebhook({ url, secret: published.webhook_secret });
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
    <>
      <Dialog
        open={open}
        onOpenChange={(next) => {
          // Trying to publish is when every missing value is worth saying.
          if (next) revealProblems();
          setOpen(next);
        }}
      >
        <DialogTrigger asChild>
          <Button size="sm" disabled={isDirty}>
            <UploadCloud className="h-4 w-4" aria-hidden />
            {t("publish")}
          </Button>
        </DialogTrigger>
        <DialogContent className={cn(DIALOG_FORM, DIALOG_SCROLL)}>
          <DialogHeader>
            <DialogTitle>{t("publishTitleVersion", { version: next })}</DialogTitle>
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

          <p className="text-muted-foreground text-xs">
            {trigger === null ? t("publishStartsByHand") : t("publishTrigger", { trigger })}
          </p>
          {live !== null && !changed && (
            <p className="bg-muted text-muted-foreground rounded-md px-3 py-2 text-xs">
              {t("publishNothingChanged", { version: live })}
            </p>
          )}
          {clientProblems.length > 0 && (
            <p className="text-muted-foreground text-xs">{t("publishBlocked")}</p>
          )}
          {isDirty && <p className="text-muted-foreground text-xs">{t("publishSaving")}</p>}
          <ProblemsFooter
            problems={problems}
            names={nodeNames(graph, nodeCatalog)}
            onSelectNode={selectNode}
            defaultOpen
          />

          <DialogFooter>
            <Button variant="outline" onClick={() => setOpen(false)} disabled={submitting}>
              {t("publishCancel")}
            </Button>
            <Button onClick={() => void confirm()} disabled={blocked || submitting || isDirty}>
              {t("publishConfirm")}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
      {webhook !== null && (
        <WebhookSecretDialog
          url={webhook.url}
          secret={webhook.secret}
          onClose={() => setWebhook(null)}
        />
      )}
    </>
  );
}
