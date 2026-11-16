"use client";

import { use, useState } from "react";
import { useRouter } from "next/navigation";
import {
  ArrowLeft,
  ClipboardCheck,
  FlaskConical,
  ListChecks,
  Settings2,
  Sparkles,
} from "lucide-react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { useWorkspaceFullscreen } from "@/hooks/use-workspace-fullscreen";
import { WorkspaceFullscreenButton } from "@/components/ui/workspace-fullscreen-button";
import { cn } from "@/lib/utils";

import { CaseEditorDialog, type CaseCopy } from "@/components/datasets/case-editor-dialog";
import { draftOf, EMPTY_DRAFT, type CaseDraft } from "@/components/datasets/case-form";
import { CasesTable } from "@/components/datasets/cases-table";
import { CasesToolbar } from "@/components/datasets/cases-toolbar";
import { DatasetHeader } from "@/components/datasets/dataset-header";
import { DatasetShareDialog } from "@/components/datasets/dataset-share-dialog";
import { EditDatasetDialog } from "@/components/datasets/edit-dataset-dialog";
import { EmptyCases } from "@/components/datasets/empty-cases";
import { HelperSettings } from "@/components/datasets/helper-settings";
import { GenerateCasesDialog } from "@/components/datasets/generate-cases-dialog";
import { GeneratePanel } from "@/components/datasets/generate-panel";
import { ReviewPanel } from "@/components/datasets/review-panel";
import { GradingPanel, type GradingCopy } from "@/components/datasets/grading-panel";
import { UnsavedCopiesBanner } from "@/components/datasets/unsaved-copies-banner";
import { VersionSelect } from "@/components/datasets/version-select";
import { DatasetEvalsPanel, DatasetRunEvalsButton } from "@/components/evals/dataset-evals-panel";
import { DatasetLoading } from "@/components/datasets/dataset-loading";
import { ErrorState } from "@/components/states";
import {
  Button,
  ConfirmDialog,
  ListCard,
  PAGE_SIZE,
  Pager,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui";
import {
  useDataset,
  useDatasetCase,
  useDatasetCases,
  useDatasetVersions,
} from "@/hooks/use-datasets";
import { usePermissions } from "@/hooks/use-permissions";
import { useUrlOverlay, useUrlState } from "@/hooks/use-url-state";
import { ResourceUnavailable } from "@/components/states/resource-unavailable";
import { ApiError, getErrorMessage } from "@/lib/api-error";
import { ROUTES } from "@/lib/constants";
import { copyKey, readCopies, removeCopy, type UnsavedCopy } from "@/lib/unsaved-copies";
import { useOrgStore } from "@/stores/org-store";
import { useUnsavedChangesStore } from "@/stores/unsaved-changes-store";
import type { DatasetCase, DatasetCaseContent } from "@/types/datasets";
import { Perm } from "@/types/permissions";

interface PageProps {
  params: Promise<{ id: string }>;
}

/** Existing deep links remain valid within the three workspace sections. */
const TABS = ["cases", "generated", "grading", "evals", "review", "settings", "results"];

/**
 * What the case dialog is showing: a new case, or one from the list - picked up
 * from an unsaved edit kept in this browser, when it is restored.
 */
type Editing = { draft: CaseDraft; item: DatasetCase | null; startFrom?: CaseCopy } | null;

/** Which of the header menu's dialogs is open. */
type Dialog = "details" | "share" | "delete" | null;

/**
 * One dataset: its cases at a version, and every way to change them.
 *
 * An older version is shown read-only - it is what an eval run answered, and it
 * does not change. Every change made from the newest one is a new version.
 */
export default function DatasetPage({ params }: PageProps) {
  const { id } = use(params);
  const t = useTranslations("datasets");
  const tc = useTranslations("common");
  const tErrors = useTranslations("errors");
  const tUnsaved = useTranslations("unsaved");
  const router = useRouter();
  const { ref: workspaceRef, expanded, toggle } = useWorkspaceFullscreen();
  const [tabParam, setTabParam] = useUrlState("tab");
  const tab = tabParam !== null && TABS.includes(tabParam) ? tabParam : "cases";
  const setTab = (next: string) => setTabParam(next === "cases" ? null : next);
  const [versionParam, setVersionParam] = useUrlState("version");
  const version =
    versionParam !== null && Number.isInteger(Number(versionParam)) ? Number(versionParam) : null;
  const [linked, caseView] = useUrlOverlay("case");
  const [page, setPage] = useState(0);
  const [editing, setEditing] = useState<Editing>(null);
  const [dialog, setDialog] = useState<Dialog>(null);
  const [generating, setGenerating] = useState(false);
  const [gradingUnsaved, setGradingUnsaved] = useState(false);
  const leave = useUnsavedChangesStore((state) => state.leave);
  const organization = useOrgStore((state) => state.activeOrgId) ?? "default";
  // Read once, when the dataset arrives: a change made since is on screen, not to restore.
  const [copies, setCopies] = useState<UnsavedCopy[] | null>(null);
  const [gradingRestore, setGradingRestore] = useState<{ value: GradingCopy; at: number }>();
  const [restoring, setRestoring] = useState<UnsavedCopy | null>(null);
  const restoringCase = useDatasetCase(id, restoring?.place.slice("case:".length) ?? null);
  const { dataset, error: datasetError, update, remove } = useDataset(id);
  // Every read behind the Evals tab and the run it starts takes runs:view.
  const canViewRuns = usePermissions().can(Perm.runsView);
  const { versions } = useDatasetVersions(id);
  const linkedCase = useDatasetCase(id, linked);
  // A link to one case opens it once it arrives, as reading it from the list would;
  // closing it leaves the page on the list rather than reopening it.
  const [opened, setOpened] = useState<string | null>(null);
  if (linked !== null && linkedCase.kase !== undefined && opened !== linked) {
    setOpened(linked);
    setEditing({ draft: draftOf(linkedCase.kase), item: linkedCase.kase });
  }
  // Back from an open case leaves its entry; the case closes with it.
  if (linked === null && opened !== null) {
    setOpened(null);
    if (editing?.item) setEditing(null);
  }
  const openCase = (item: DatasetCase) => {
    setOpened(item.case_id);
    setEditing({ draft: draftOf(item), item });
    caseView.open(item.case_id);
  };
  if (restoring !== null && restoringCase.kase !== undefined) {
    setRestoring(null);
    setEditing({
      draft: draftOf(restoringCase.kase),
      item: restoringCase.kase,
      startFrom: restoring.value as CaseCopy,
    });
  }
  if (restoring !== null && restoringCase.error) {
    setRestoring(null);
    removeCopy(restoring.key);
    toast.info(tUnsaved("caseGone"));
  }
  if (dataset !== undefined && copies === null) {
    // Only an editor's own edits are kept, and only an editor is offered them back.
    setCopies(dataset.can_edit ? readCopies(organization, id) : []);
  }
  const cases = useDatasetCases(id, { version, skip: page * PAGE_SIZE, limit: PAGE_SIZE });
  const pageCount = Math.max(1, Math.ceil(cases.total / PAGE_SIZE));
  // Removing the last case of the last page leaves that page empty; step back to
  // the page that still exists, the adjust-state-while-rendering way.
  if (!cases.isLoading && page >= pageCount) setPage(pageCount - 1);

  if (datasetError instanceof ApiError && [403, 404].includes(datasetError.status)) {
    return <ResourceUnavailable back={ROUTES.DATASETS} label={tc("back")} />;
  }
  if (datasetError) {
    return <ErrorState description={getErrorMessage(datasetError, tErrors)} />;
  }
  if (dataset === undefined) {
    return <DatasetLoading />;
  }

  const editable = dataset.can_edit && version === null;
  // A link reaches a reader too, who may have no such tab.
  const shown =
    (tab === "generated" && !dataset.can_edit) || (tab === "evals" && !canViewRuns)
      ? "cases"
      : tab === "results"
        ? "review"
        : tab;
  const primaryTab =
    shown === "generated"
      ? "cases"
      : shown === "grading" || shown === "settings"
        ? "settings"
        : shown === "evals" || shown === "review"
          ? "results"
          : "cases";
  const keep = (place: string) => ({
    key: copyKey(organization, id, place),
    base: dataset.latest_version,
  });
  const showTab = (next: string) => leave(() => setTab(next));
  const restoreCopy = (copy: UnsavedCopy) => {
    setCopies((kept) => kept?.filter((one) => one.key !== copy.key) ?? null);
    if (copy.place === "grading") {
      setGradingRestore({ value: copy.value as GradingCopy, at: Date.now() });
      setTab("grading");
    } else if (copy.place === "case:new") {
      setEditing({ draft: EMPTY_DRAFT, item: null, startFrom: copy.value as CaseCopy });
    } else {
      setRestoring(copy);
    }
  };
  const save = (content: DatasetCaseContent) =>
    editing?.item
      ? cases.update.mutateAsync({ caseId: editing.item.case_id, content })
      : cases.add.mutateAsync(content);

  return (
    <div className="flex flex-1 flex-col gap-4">
      <DatasetHeader
        dataset={dataset}
        version={version}
        onImport={editable ? (file) => cases.importFile.mutateAsync(file) : undefined}
        onEditDetails={() => setDialog("details")}
        onShare={() => setDialog("share")}
        onDelete={() => setDialog("delete")}
        actions={
          // The button decides for itself, so a reader missing only runs:view
          // sees it disabled, saying why.
          dataset.case_count > 0 ? <DatasetRunEvalsButton datasetId={id} /> : undefined
        }
      />

      {copies !== null && copies.length > 0 && (
        <UnsavedCopiesBanner
          copies={copies}
          latest={dataset.latest_version}
          onRestore={restoreCopy}
          onDiscard={(copy) => {
            removeCopy(copy.key);
            setCopies(copies.filter((one) => one.key !== copy.key));
          }}
        />
      )}
      <div
        ref={workspaceRef}
        role={expanded ? "dialog" : undefined}
        aria-modal={expanded || undefined}
        aria-label={dataset.name}
        className={cn(
          "flex min-w-0 flex-1 flex-col",
          expanded && "bg-background fixed inset-0 z-40 overflow-y-auto p-4 sm:p-6",
        )}
      >
        <Tabs
          value={primaryTab}
          onValueChange={(next) => showTab(next === "results" ? "review" : next)}
          className="flex flex-1 flex-col gap-4"
        >
          {expanded && <h2 className="mb-4 text-lg font-semibold break-words">{dataset.name}</h2>}
          <div className="flex min-w-0 items-center gap-2">
            <TabsList className="min-w-0 flex-1">
              <TabsTrigger value="cases">
                <ListChecks className="mr-1.5 size-4 shrink-0" aria-hidden />
                {t("cases")}
              </TabsTrigger>
              <TabsTrigger value="results" data-tour="datasets-results-tab">
                <ClipboardCheck className="size-4" aria-hidden />
                {t("workspace.results")}
              </TabsTrigger>
              <TabsTrigger value="settings" data-tour="datasets-settings-tab">
                <Settings2 className="size-4" aria-hidden />
                {t("settingsTab")}
                {gradingUnsaved && (
                  <span
                    className="bg-primary ml-1.5 size-1.5 rounded-full"
                    role="img"
                    aria-label={t("scoring.unsaved")}
                  />
                )}
              </TabsTrigger>
            </TabsList>
            <WorkspaceFullscreenButton expanded={expanded} onToggle={toggle} />
          </div>
          <TabsContent value="cases" className="flex flex-1 flex-col gap-4">
            {shown === "generated" && dataset.can_edit ? (
              <>
                <div className="flex flex-wrap items-center gap-3">
                  <Button variant="ghost" size="sm" onClick={() => showTab("cases")}>
                    <ArrowLeft className="size-4" aria-hidden />
                    {t("workspace.backToCases")}
                  </Button>
                  <span className="text-muted-foreground text-sm">
                    {t("generatedTab", { count: dataset.pending_proposals })}
                  </span>
                </div>
                <GeneratePanel datasetId={id} />
              </>
            ) : (
              <ListCard
                fill
                namedByPage
                contentClassName="p-0"
                title={t("cases")}
                counted={t("caseCount", { count: cases.total })}
                controls={
                  <div className="flex min-w-0 flex-wrap items-center gap-2">
                    {versions.length > 0 && (
                      <VersionSelect
                        versions={versions}
                        latest={dataset.latest_version}
                        value={version}
                        onChange={(next) =>
                          leave(() => {
                            setVersionParam(next === null ? null : String(next));
                            setPage(0);
                          })
                        }
                      />
                    )}
                    {editable && dataset.pending_proposals > 0 && (
                      <Button variant="outline" size="sm" onClick={() => showTab("generated")}>
                        <Sparkles className="size-4" aria-hidden />
                        {t("generatedTab", { count: dataset.pending_proposals })}
                      </Button>
                    )}
                    {dataset.can_edit &&
                      (cases.cases.length > 0 || cases.isLoading || version !== null) && (
                        <CasesToolbar
                          datasetId={id}
                          disabled={!editable}
                          onAdd={() => setEditing({ draft: EMPTY_DRAFT, item: null })}
                          onImport={(file) => cases.importFile.mutateAsync(file)}
                          onGenerate={() => setGenerating(true)}
                        />
                      )}
                  </div>
                }
              >
                {linkedCase.error && (
                  <p role="alert" className="text-muted-foreground mb-3 text-sm">
                    {t("linkedCaseGone")}
                  </p>
                )}
                {cases.isLoading ? (
                  <CasesTable cases={[]} loading onOpen={openCase} />
                ) : cases.error ? (
                  <ErrorState
                    description={getErrorMessage(cases.error, tErrors)}
                    cta={{ label: tc("retry"), onClick: () => void cases.refetch() }}
                  />
                ) : cases.cases.length === 0 ? (
                  <EmptyCases
                    datasetId={id}
                    onAddCase={
                      editable ? () => setEditing({ draft: EMPTY_DRAFT, item: null }) : undefined
                    }
                    onImport={editable ? (file) => cases.importFile.mutateAsync(file) : undefined}
                    onGenerate={editable ? () => setGenerating(true) : undefined}
                  />
                ) : (
                  <div className="flex flex-1 flex-col gap-4">
                    <CasesTable
                      cases={cases.cases}
                      offset={page * PAGE_SIZE}
                      activeCaseId={editing?.item?.case_id}
                      onOpen={openCase}
                      onRemove={editable ? (item) => cases.remove.mutate(item.case_id) : undefined}
                    />
                    <Pager
                      page={page}
                      pageCount={pageCount}
                      matched={cases.total}
                      total={cases.total}
                      onPage={setPage}
                      counted={t("caseCount", { count: cases.total })}
                    />
                  </div>
                )}
              </ListCard>
            )}
          </TabsContent>
          {/* Kept mounted while another tab is open, so a card's unsaved change
            survives looking at the cases it is about. */}
          <TabsContent
            value="settings"
            forceMount
            className="flex flex-1 flex-col data-[state=inactive]:hidden"
          >
            <GradingPanel
              dataset={dataset}
              onContinue={canViewRuns && dataset.can_run ? () => showTab("evals") : undefined}
              onDirtyChange={setGradingUnsaved}
              localCopy={dataset.can_edit ? keep("grading") : undefined}
              restore={gradingRestore}
            />
            {dataset.can_edit && (
              <section className="mt-6 space-y-4">
                <div>
                  <h2 className="text-base font-semibold">{t("workspace.helpers")}</h2>
                  <p className="text-muted-foreground mt-1 text-sm">{t("workspace.helpersHint")}</p>
                </div>
                <div className="grid items-stretch gap-4 xl:grid-cols-2">
                  <HelperSettings dataset={dataset} kind="generator" />
                  <HelperSettings dataset={dataset} kind="improver" />
                </div>
              </section>
            )}
          </TabsContent>
          <TabsContent value="results" className="flex flex-1 flex-col gap-4">
            {canViewRuns && (
              <div className="flex flex-wrap gap-2" aria-label={t("workspace.results")}>
                <Button
                  size="sm"
                  variant={shown === "evals" ? "secondary" : "ghost"}
                  aria-pressed={shown === "evals"}
                  onClick={() => showTab("evals")}
                >
                  <FlaskConical className="size-4" aria-hidden />
                  {t("workspace.testRuns")}
                </Button>
                <Button
                  size="sm"
                  variant={shown === "review" ? "secondary" : "ghost"}
                  aria-pressed={shown === "review"}
                  data-tour="datasets-review-tab"
                  onClick={() => showTab("review")}
                >
                  <ClipboardCheck className="size-4" aria-hidden />
                  {t("workspace.reviewAnswers")}
                </Button>
              </div>
            )}
            {shown === "evals" && canViewRuns ? (
              <DatasetEvalsPanel
                datasetId={id}
                title={t("workspace.testRuns")}
                onReview={() => showTab("review")}
              />
            ) : (
              <ReviewPanel dataset={dataset} />
            )}
          </TabsContent>
        </Tabs>
      </div>

      {generating && editable && (
        <GenerateCasesDialog
          datasetId={id}
          open
          onOpenChange={setGenerating}
          onStarted={() => setTab("generated")}
        />
      )}
      {dialog === "details" && (
        <EditDatasetDialog dataset={dataset} onOpenChange={() => setDialog(null)} update={update} />
      )}
      {dialog === "share" && (
        <DatasetShareDialog dataset={dataset} onOpenChange={() => setDialog(null)} />
      )}
      {dialog === "delete" && (
        <ConfirmDialog
          open
          onOpenChange={() => setDialog(null)}
          title={tc("deleteNamedConfirm", { name: dataset.name })}
          description={t("deleteBody")}
          confirmLabel={tc("delete")}
          destructive
          loading={remove.isPending}
          onConfirm={async () => {
            await remove.mutateAsync();
            router.push(ROUTES.DATASETS);
          }}
        />
      )}

      {editing !== null && (
        <CaseEditorDialog
          key={editing.item?.id ?? "new"}
          open
          onOpenChange={(open) => {
            if (open) return;
            if (editing.item && linked !== null) caseView.close();
            setEditing(null);
          }}
          initial={editing.draft}
          viewing={editing.item ?? undefined}
          title={editing.item === null ? t("addCase") : t("case")}
          nextVersion={dataset.latest_version + 1}
          scoring={dataset.scoring}
          knownTools={[
            ...new Set(cases.cases.flatMap((item) => item.expected_tool_calls.map((c) => c.tool))),
          ]}
          onSave={editable && !editing.item?.masked ? save : undefined}
          startFrom={editing.startFrom}
          localCopy={
            editable && !editing.item?.masked
              ? keep(editing.item === null ? "case:new" : `case:${editing.item.case_id}`)
              : undefined
          }
          twins={
            editing.item === null
              ? {
                  find: cases.findTwin,
                  open: openCase,
                }
              : undefined
          }
        />
      )}
    </div>
  );
}
