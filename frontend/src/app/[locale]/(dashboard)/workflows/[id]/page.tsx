"use client";

import { use, useEffect, useRef, useState } from "react";
import Link from "next/link";
import {
  Activity,
  Download,
  History,
  MoreHorizontal,
  Settings2,
  Workflow,
  Zap,
} from "lucide-react";
import { useTranslations } from "next-intl";

import { PageHeader } from "@/components/dashboard/page-header";
import { LiveRun, StaleRun, WorkflowCanvas } from "@/components/workflows/canvas";
import {
  ConflictBanner,
  DebugRun,
  DraftAutosave,
  PublishDialog,
  WorkflowSettingsForm,
  ChatButton,
  RunButton,
  VersionHistory,
  useRestoreVersion,
} from "@/components/workflows/editor";
import { TriggerPanel } from "@/components/workflows/triggers";
import { NodeEditorDialog, StepDataFeed } from "@/components/workflows/node-editor";
import {
  Button,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  ListCard,
  ListCardEmpty,
  Sheet,
  SheetClose,
  SheetContent,
  SheetHeader,
  SheetTitle,
  Skeleton,
} from "@/components/ui";
import {
  useNodeCatalog,
  useUrlState,
  useWorkflow,
  useWorkflowActions,
  useWorkflowExport,
} from "@/hooks";
import { TagsEditor } from "@/components/workflows/tags-editor";
import { ActiveSwitch } from "@/components/workflows/editor/active-switch";
import { WorkflowDescription } from "@/components/workflows/editor/workflow-description";
import { WorkflowStatus } from "@/components/workflows/editor/workflow-status";
import { WorkflowTitle } from "@/components/workflows/editor/workflow-title";
import { ROUTES } from "@/lib/constants";
import type { WorkflowGraph } from "@/lib/workflows/types";
import { useWorkflowEditorStore } from "@/stores";

interface PageProps {
  params: Promise<{ id: string }>;
}

/** The graph a workflow nobody has edited starts from, since its `draft_graph` is null. */
const EMPTY_GRAPH: WorkflowGraph = {
  entry_node_id: "",
  nodes: [],
  edges: [],
  bindings: [],
  scopes: [],
};

/**
 * The workflow editor shell — the canvas across the page's whole width, a step's
 * settings in a dialog over it, the publish control, conflict banner and version
 * history.
 *
 * It loads the workflow (`WorkflowDetail`, carrying `draft_graph`/`draft_revision`)
 * and the node catalog into TanStack Query and hands the coordination facts
 * (`workflowId`, `draft_revision`) to the editor store; the graph itself lives in
 * the store, seeded once per workflow. The editor tree is keyed on the workflow id
 * so a switch remounts it, and the store bumps its generation on every `load`.
 *
 * The seed is deliberately once-per-id: autosave's own success invalidates the
 * detail query, and reseeding the store from that background refetch would throw
 * away edits made while the save was in flight. The store's revision is advanced
 * by autosave, not by the refetch.
 *
 * A caller who may not edit this workflow gets a read-only editor: the canvas
 * renders with `readOnly`, a step's dialog opens read-only, and the edit chrome —
 * **Add step**, the autosave/publish actions and the conflict banner — is not
 * rendered at all, so no autosave fires to 404. Whether they may is the workflow's own `can_edit`,
 * resolved server-side: a role's `workflows:edit` says nothing about *this*
 * workflow - a builder views every one and edits only their own and shared ones,
 * and a grant widens a role for one - and an archived workflow is read-only for
 * everybody. This is the "not rendered, then refused" rule: never show a control
 * the server would refuse. Every write is still re-checked server-side.
 */
export default function WorkflowEditorPage({ params }: PageProps) {
  const { id } = use(params);
  const t = useTranslations("pages.workflows");
  const { workflow, isLoading, saveDraft, publish, restore } = useWorkflow(id);
  const actions = useWorkflowActions();
  const exporting = useWorkflowExport();
  const restoreVersion = useRestoreVersion(restore.mutateAsync);
  const { nodes, isLoading: catalogLoading } = useNodeCatalog();
  const canEdit = workflow?.can_edit === true;
  const load = useWorkflowEditorStore((state) => state.load);
  const seedGraph = useWorkflowEditorStore((state) => state.seedGraph);
  const draft = useWorkflowEditorStore((state) => state.graph);
  const teardown = useWorkflowEditorStore((state) => state.teardown);
  const seededId = useRef<string | null>(null);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [triggersOpen, setTriggersOpen] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  // The test run started from Run, shown on the canvas until the next edit.
  const [liveRunId, setLiveRunId] = useState<string | null>(null);
  // That run once an edit ended its overlay: its page stays one click away.
  const [staleRunId, setStaleRunId] = useState<string | null>(null);
  const startedRun = (runId: string) => {
    setStaleRunId(null);
    setLiveRunId(runId);
  };
  // A past run whose data "Debug in editor" brings into the draft.
  const [debugRunId, setDebugRunId] = useUrlState("debug");

  useEffect(() => {
    if (workflow && seededId.current !== workflow.id) {
      seededId.current = workflow.id;
      load({ workflowId: workflow.id, expectedRevision: workflow.draft_revision });
      seedGraph(workflow.draft_graph ?? EMPTY_GRAPH);
    }
  }, [workflow, load, seedGraph]);

  // The store is torn down (not merely reset) on unmount, so no cross-workflow
  // or cross-organization state survives leaving the editor.
  useEffect(
    () => () => {
      teardown();
      seededId.current = null;
    },
    [teardown],
  );

  // The canvas waits for the catalog too: a card drawn without its definition
  // has no ports, and its connections cannot find where to attach (xyflow 008).
  if (isLoading || catalogLoading) {
    return (
      <div className="space-y-6">
        <Skeleton className="h-8 w-64" />
        <Skeleton className="h-96 w-full" />
      </div>
    );
  }

  if (!workflow) {
    return (
      <div className="space-y-6">
        <PageHeader
          title={t("notFound")}
          breadcrumbs={[{ label: t("title"), href: ROUTES.WORKFLOWS }, { label: t("notFound") }]}
        />
        <ListCard title={t("notFound")} counted={null}>
          <ListCardEmpty icon={Workflow} title={t("notFound")} description={t("notFoundDetail")} />
        </ListCard>
      </div>
    );
  }

  const statusBadge = (
    <div className="flex flex-wrap items-center gap-2">
      <WorkflowStatus workflow={workflow} draft={draft} />
      <TagsEditor
        tags={workflow.tags}
        canEdit={canEdit}
        onChange={(tags) => actions.update.mutate({ id: workflow.id, update: { tags } })}
      />
      {canEdit && <DraftAutosave saveDraft={saveDraft.mutateAsync} />}
    </div>
  );

  return (
    // Fills what the shell's `main` leaves: the editor is a workspace, and a canvas
    // in a fixed-height box scrolls the page instead of the graph.
    <div key={workflow.id} className="flex min-h-[40rem] flex-1 flex-col gap-3 pb-4">
      <PageHeader
        // The canvas is the page: the header gives it the height a list page
        // would keep for breathing room.
        className="mb-0 md:mb-0"
        title={
          <WorkflowTitle
            name={workflow.name}
            canEdit={canEdit}
            onRename={(name) => actions.update.mutate({ id: workflow.id, update: { name } })}
          />
        }
        description={
          // An editor is offered one to write; a reader sees none that is not there.
          canEdit || workflow.description ? (
            <WorkflowDescription
              description={workflow.description}
              canEdit={canEdit}
              onChange={(description) =>
                actions.update.mutate({ id: workflow.id, update: { description } })
              }
            />
          ) : undefined
        }
        breadcrumbs={[{ label: t("title"), href: ROUTES.WORKFLOWS }, { label: workflow.name }]}
        badges={statusBadge}
        actions={
          <div className="flex items-center gap-2">
            <ActiveSwitch
              workflow={workflow}
              canEdit={canEdit}
              pending={actions.setActive.isPending}
              onChange={(active) => actions.setActive.mutate({ id: workflow.id, active })}
            />
            <Button variant="outline" asChild>
              <Link href={ROUTES.WORKFLOW_RUNS(workflow.id)}>
                <Activity className="h-4 w-4" />
                {t("runsTitle")}
              </Link>
            </Button>
            <Button variant="outline" onClick={() => setHistoryOpen(true)}>
              <History className="h-4 w-4" />
              {t("history")}
            </Button>
            {/* Looked at now and then, not on every visit: kept one click away. */}
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="outline" size="icon" aria-label={t("moreActions")}>
                  <MoreHorizontal className="h-4 w-4" />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem onSelect={() => setTriggersOpen(true)}>
                  <Zap className="h-4 w-4" />
                  {t("triggers")}
                </DropdownMenuItem>
                <DropdownMenuItem onSelect={() => setSettingsOpen(true)}>
                  <Settings2 className="h-4 w-4" />
                  {t("settings")}
                </DropdownMenuItem>
                <DropdownMenuItem
                  disabled={exporting.isPending}
                  onSelect={() => exporting.mutate({ id: workflow.id, slug: workflow.slug })}
                >
                  <Download className="h-4 w-4" />
                  {t("exportWorkflow")}
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
            {canEdit && (
              <ChatButton workflowId={workflow.id} catalog={nodes} onStarted={startedRun} />
            )}
            {canEdit && (
              <RunButton workflowId={workflow.id} catalog={nodes} onStarted={startedRun} />
            )}
            {canEdit && (
              <PublishDialog workflow={workflow} catalog={nodes} publish={publish.mutateAsync} />
            )}
          </div>
        }
      />
      {canEdit && <ConflictBanner workflowId={workflow.id} />}
      <div
        data-workflow-editor
        className="border-border bg-card relative flex min-h-0 flex-1 overflow-hidden rounded-xl border"
      >
        <div className="relative min-w-0 flex-1">
          {liveRunId === null ? (
            <WorkflowCanvas workflow={workflow} catalog={nodes} readOnly={!canEdit} />
          ) : (
            <LiveRun
              workflowId={workflow.id}
              runId={liveRunId}
              onClose={() => setLiveRunId(null)}
              onStale={() => {
                setStaleRunId(liveRunId);
                setLiveRunId(null);
              }}
            >
              <WorkflowCanvas workflow={workflow} catalog={nodes} readOnly={!canEdit} />
            </LiveRun>
          )}
          {liveRunId === null && staleRunId !== null && (
            <StaleRun
              workflowId={workflow.id}
              runId={staleRunId}
              onClose={() => setStaleRunId(null)}
            />
          )}
        </div>
      </div>
      <NodeEditorDialog workflowId={workflow.id} catalog={nodes} readOnly={!canEdit} />
      {canEdit && <StepDataFeed workflowId={workflow.id} />}
      {canEdit && debugRunId !== null && (
        <DebugRun runId={debugRunId} catalog={nodes} onDone={() => setDebugRunId(null)} />
      )}
      <Sheet open={triggersOpen} onOpenChange={setTriggersOpen}>
        <SheetContent side="right" className="w-full max-w-lg overflow-y-auto">
          <SheetHeader>
            <SheetTitle>{t("triggers")}</SheetTitle>
            <SheetClose onClick={() => setTriggersOpen(false)} />
          </SheetHeader>
          <div className="p-4">
            {/* Mounted with the sheet, so its state is read only when someone looks. */}
            {triggersOpen && (
              <TriggerPanel workflow={workflow} draft={draft} catalog={nodes} canEdit={canEdit} />
            )}
          </div>
        </SheetContent>
      </Sheet>
      <Sheet open={settingsOpen} onOpenChange={setSettingsOpen}>
        <SheetContent side="right" className="w-full max-w-lg overflow-y-auto">
          <SheetHeader>
            <SheetTitle>{t("settings")}</SheetTitle>
            <SheetClose onClick={() => setSettingsOpen(false)} />
          </SheetHeader>
          <div className="p-4">
            {settingsOpen && (
              <WorkflowSettingsForm
                workflow={workflow}
                disabled={!canEdit}
                saving={actions.saveSettings.isPending}
                onSave={(settings) =>
                  actions.saveSettings.mutate(
                    { id: workflow.id, settings },
                    { onSuccess: () => setSettingsOpen(false) },
                  )
                }
              />
            )}
          </div>
        </SheetContent>
      </Sheet>
      <Sheet open={historyOpen} onOpenChange={setHistoryOpen}>
        <SheetContent side="right" className="w-full max-w-lg overflow-y-auto">
          <SheetHeader>
            <SheetTitle>{t("history")}</SheetTitle>
            <SheetClose onClick={() => setHistoryOpen(false)} />
          </SheetHeader>
          <div className="p-4">
            <VersionHistory
              workflowId={workflow.id}
              liveVersionId={workflow.current_version_id}
              catalog={nodes}
              onRestore={canEdit ? restoreVersion : undefined}
            />
          </div>
        </SheetContent>
      </Sheet>
    </div>
  );
}
