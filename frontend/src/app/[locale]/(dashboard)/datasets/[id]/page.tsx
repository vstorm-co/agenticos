"use client";

import { use, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";

import { CaseEditorDialog } from "@/components/datasets/case-editor-dialog";
import { draftOf, EMPTY_DRAFT, type CaseDraft } from "@/components/datasets/case-form";
import { CaseRow } from "@/components/datasets/case-row";
import { DatasetHeader } from "@/components/datasets/dataset-header";
import { DatasetShareDialog } from "@/components/datasets/dataset-share-dialog";
import { EditDatasetDialog } from "@/components/datasets/edit-dataset-dialog";
import { EmptyCases } from "@/components/datasets/empty-cases";
import { ReviewPanel } from "@/components/datasets/review-panel";
import { GradingPanel } from "@/components/datasets/grading-panel";
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
import { getErrorMessage } from "@/lib/api-error";
import { ROUTES } from "@/lib/constants";
import type { DatasetCase, DatasetCaseContent } from "@/types/datasets";
import { Perm } from "@/types/permissions";

interface PageProps {
  params: Promise<{ id: string }>;
}

/** The tabs `?tab=` may open, in the order they are drawn. */
const TABS = ["cases", "grading", "evals", "review"];

/** What the case dialog is showing: a new case, or one from the list. */
type Editing = { draft: CaseDraft; item: DatasetCase | null } | null;

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
  const router = useRouter();
  const query = useSearchParams();
  const asked = query.get("tab");
  const linked = query.get("case");
  const [version, setVersion] = useState<number | null>(null);
  const [page, setPage] = useState(0);
  const [editing, setEditing] = useState<Editing>(null);
  const [dialog, setDialog] = useState<Dialog>(null);
  const [gradingUnsaved, setGradingUnsaved] = useState(false);
  const { dataset, error: datasetError, update, remove } = useDataset(id);
  // Every read behind the Evals tab and the run it starts takes runs:view.
  const canViewRuns = usePermissions().can(Perm.runsView);
  const { versions } = useDatasetVersions(id);
  const linkedCase = useDatasetCase(id, linked);
  // A link to one case opens it once it arrives, as reading it from the list would;
  // closing it leaves the page on the list rather than reopening it.
  const [opened, setOpened] = useState<string | null>(null);
  if (linkedCase.kase !== undefined && opened !== linked) {
    setOpened(linked);
    setEditing({ draft: draftOf(linkedCase.kase), item: linkedCase.kase });
  }
  const cases = useDatasetCases(id, { version, skip: page * PAGE_SIZE, limit: PAGE_SIZE });
  const pageCount = Math.max(1, Math.ceil(cases.total / PAGE_SIZE));
  // Removing the last case of the last page leaves that page empty; step back to
  // the page that still exists, the adjust-state-while-rendering way.
  if (!cases.isLoading && page >= pageCount) setPage(pageCount - 1);

  if (datasetError) {
    return <ErrorState description={getErrorMessage(datasetError, tErrors)} />;
  }
  if (dataset === undefined) {
    return <LoadingState variant="skeleton-panel" rows={3} />;
  }

  const editable = dataset.can_edit && version === null;
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
          canViewRuns && dataset.case_count > 0 ? (
            <DatasetRunEvalsButton datasetId={id} />
          ) : undefined
        }
      />

      <Tabs
        defaultValue={asked !== null && TABS.includes(asked) ? asked : "cases"}
        className="space-y-4"
      >
        <TabsList>
          <TabsTrigger value="cases">{t("cases")}</TabsTrigger>
          <TabsTrigger value="grading" data-tour="datasets-grading-tab">
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
              {t("evals")}
            </TabsTrigger>
          )}
          <TabsTrigger value="review" data-tour="datasets-review-tab">
            {t("scoring.scores")}
          </TabsTrigger>
        </TabsList>
        <TabsContent value="cases">
          <ListCard
            title={t("cases")}
            counted={t("caseCount", { count: cases.total })}
            controls={
              versions.length > 0 && (
                <VersionSelect
                  versions={versions}
                  latest={dataset.latest_version}
                  value={version}
                  onChange={(next) => {
                    setVersion(next);
                    setPage(0);
                  }}
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
              />
            ) : (
              <div className="space-y-4">
                <ul>
                  {cases.cases.map((item) => (
                    <CaseRow
                      key={item.id}
                      item={item}
                      onOpen={() => setEditing({ draft: draftOf(item), item })}
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
        {/* Kept mounted while another tab is open, so a card's unsaved change
            survives looking at the cases it is about. */}
        <TabsContent value="grading" forceMount className="data-[state=inactive]:hidden">
          <GradingPanel dataset={dataset} onDirtyChange={setGradingUnsaved} />
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
            if (!open) setEditing(null);
          }}
          initial={editing.draft}
          viewing={editing.item ?? undefined}
          title={editing.item === null ? t("addCase") : t("case")}
          nextVersion={dataset.latest_version + 1}
          scoring={dataset.scoring}
          knownTools={[
            ...new Set(cases.cases.flatMap((item) => item.expected_tool_calls.map((c) => c.tool))),
          ]}
          onSave={editable ? save : undefined}
          twins={
            editing.item === null
              ? {
                  find: cases.findTwin,
                  open: (twin) => setEditing({ draft: draftOf(twin), item: twin }),
                }
              : undefined
          }
        />
      )}
    </div>
  );
}
