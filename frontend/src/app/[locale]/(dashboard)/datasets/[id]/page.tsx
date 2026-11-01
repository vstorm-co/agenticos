"use client";

import { use, useState } from "react";
import { useRouter } from "next/navigation";
import { ClipboardCheck, FlaskConical, ListChecks, Scale, Sparkles } from "lucide-react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { CaseEditorDialog, type CaseCopy } from "@/components/datasets/case-editor-dialog";
import { draftOf, EMPTY_DRAFT, type CaseDraft } from "@/components/datasets/case-form";
import { CaseRow } from "@/components/datasets/case-row";
import { DatasetHeader } from "@/components/datasets/dataset-header";
import { DatasetShareDialog } from "@/components/datasets/dataset-share-dialog";
import { EditDatasetDialog } from "@/components/datasets/edit-dataset-dialog";
import { EmptyCases } from "@/components/datasets/empty-cases";
import { GeneratePanel } from "@/components/datasets/generate-panel";
import { ReviewPanel } from "@/components/datasets/review-panel";
import { GradingPanel, type GradingCopy } from "@/components/datasets/grading-panel";
import { UnsavedCopiesBanner } from "@/components/datasets/unsaved-copies-banner";
import { VersionSelect } from "@/components/datasets/version-select";
import { DatasetEvalsPanel, DatasetRunEvalsButton } from "@/components/evals/dataset-evals-panel";
import { ErrorState, LoadingState } from "@/components/states";
import {
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

/** The tabs `?tab=` may open, in the order they are drawn. */
const TABS = ["cases", "generated", "grading", "evals", "review"];

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
    return <LoadingState variant="skeleton-panel" rows={3} />;
  }

  const editable = dataset.can_edit && version === null;
  // A link reaches a reader too, who may have no such tab.
  const shown =
    (tab === "generated" && !dataset.can_edit) || (tab === "evals" && !canViewRuns) ? "cases" : tab;
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
    <div className="space-y-6">
      <DatasetHeader
        dataset={dataset}
        version={version}
        onAddCase={editable ? () => setEditing({ draft: EMPTY_DRAFT, item: null }) : undefined}
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

      {(version === null || version === dataset.latest_version) &&
        dataset.stats?.train_cases !== undefined &&
        dataset.stats.holdout_cases !== undefined && (
          <p className="text-muted-foreground text-sm">
            {t("improvementSplit.counts", {
              train: dataset.stats.train_cases,
              holdout: dataset.stats.holdout_cases,
            })}
          </p>
        )}
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
      <Tabs value={shown} onValueChange={showTab} className="space-y-4">
        <TabsList>
          <TabsTrigger value="cases">
            <ListChecks className="mr-1.5 size-4 shrink-0" aria-hidden />
            {t("cases")}
          </TabsTrigger>
          {dataset.can_edit && (
            <TabsTrigger value="generated" data-tour="datasets-generated-tab">
              <Sparkles className="mr-1.5 size-4 shrink-0" aria-hidden />
              {t("generatedTab", { count: dataset.pending_proposals })}
            </TabsTrigger>
          )}
          <TabsTrigger value="grading" data-tour="datasets-grading-tab">
            <Scale className="mr-1.5 size-4 shrink-0" aria-hidden />
            {t("scoring.title")}
            {gradingUnsaved && (
              <span
                className="bg-primary ml-1.5 size-1.5 rounded-full"
                role="img"
                aria-label={t("scoring.unsaved")}
              />
            )}
          </TabsTrigger>
          {canViewRuns && (
            <TabsTrigger value="evals" data-tour="datasets-evals-tab">
              <FlaskConical className="mr-1.5 size-4 shrink-0" aria-hidden />
              {t("evals")}
            </TabsTrigger>
          )}
          <TabsTrigger value="review" data-tour="datasets-review-tab">
            <ClipboardCheck className="mr-1.5 size-4 shrink-0" aria-hidden />
            {t("scoring.scores")}
          </TabsTrigger>
        </TabsList>
        <TabsContent value="cases">
          <ListCard
            namedByPage
            title={t("cases")}
            counted={t("caseCount", { count: cases.total })}
            controls={
              versions.length > 0 && (
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
              )
            }
          >
            {linkedCase.error && (
              <p role="alert" className="text-muted-foreground mb-3 text-sm">
                {t("linkedCaseGone")}
              </p>
            )}
            {cases.isLoading ? (
              <LoadingState variant="skeleton-cards" rows={2} />
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
                onGenerate={editable ? () => showTab("generated") : undefined}
              />
            ) : (
              <div className="space-y-4">
                <ul>
                  {cases.cases.map((item) => (
                    <CaseRow
                      key={item.id}
                      item={item}
                      onOpen={() => openCase(item)}
                      onRemove={editable ? () => cases.remove.mutate(item.case_id) : undefined}
                    />
                  ))}
                </ul>
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
        </TabsContent>
        {dataset.can_edit && (
          <TabsContent value="generated">
            <GeneratePanel datasetId={id} />
          </TabsContent>
        )}
        {/* Kept mounted while another tab is open, so a card's unsaved change
            survives looking at the cases it is about. */}
        <TabsContent value="grading" forceMount className="data-[state=inactive]:hidden">
          <GradingPanel
            dataset={dataset}
            onDirtyChange={setGradingUnsaved}
            localCopy={dataset.can_edit ? keep("grading") : undefined}
            restore={gradingRestore}
          />
        </TabsContent>
        {canViewRuns && (
          <TabsContent value="evals">
            <DatasetEvalsPanel datasetId={id} title={t("evals")} />
          </TabsContent>
        )}
        <TabsContent value="review">
          <ReviewPanel dataset={dataset} />
        </TabsContent>
      </Tabs>

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
