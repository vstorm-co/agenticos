"use client";

import { use, useState } from "react";
import { useSearchParams } from "next/navigation";
import { FlaskConical, Pencil, Plus } from "lucide-react";
import { useTranslations } from "next-intl";

import { PageHeader } from "@/components/dashboard/page-header";
import { CaseEditorDialog } from "@/components/datasets/case-editor-dialog";
import { draftOf, EMPTY_DRAFT, type CaseDraft } from "@/components/datasets/case-form";
import { CaseRow } from "@/components/datasets/case-row";
import { DatasetFileActions } from "@/components/datasets/dataset-file-actions";
import { EditDatasetDialog } from "@/components/datasets/edit-dataset-dialog";
import { ScoresPanel } from "@/components/datasets/scores-panel";
import { ScoringPanel } from "@/components/datasets/scoring-panel";
import { VersionSelect } from "@/components/datasets/version-select";
import { SharingPanel } from "@/components/sharing/sharing-panel";
import { ErrorState, LoadingState } from "@/components/states";
import {
  Badge,
  Button,
  ListCard,
  ListCardEmpty,
  PAGE_SIZE,
  Pager,
  Tabs,
  TabsContent,
  TabsList,
  TabsTrigger,
} from "@/components/ui";
import { useDataset, useDatasetCases, useDatasetVersions } from "@/hooks/use-datasets";
import { getErrorMessage } from "@/lib/api-error";
import { ROUTES } from "@/lib/constants";
import type { DatasetCase, DatasetCaseContent } from "@/types/datasets";

interface PageProps {
  params: Promise<{ id: string }>;
}

const TABS = ["cases", "scoring", "scores"];

/** What the case dialog is showing: a new case, or one from the list. */
type Editing = { draft: CaseDraft; item: DatasetCase | null } | null;

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
  const asked = useSearchParams().get("tab");
  const [version, setVersion] = useState<number | null>(null);
  const [page, setPage] = useState(0);
  const [editing, setEditing] = useState<Editing>(null);
  const [editingDetails, setEditingDetails] = useState(false);
  const { dataset, error: datasetError, update } = useDataset(id);
  const { versions } = useDatasetVersions(id);
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
      <PageHeader
        title={dataset.name}
        description={dataset.description ?? undefined}
        breadcrumbs={[{ label: t("title"), href: ROUTES.DATASETS }, { label: dataset.name }]}
        badges={
          dataset.latest_version > 0 ? (
            <Badge variant="outline">
              {t("versionNumber", { number: dataset.latest_version })}
            </Badge>
          ) : undefined
        }
        actions={
          dataset.can_edit ? (
            <>
              <Button variant="outline" onClick={() => setEditingDetails(true)}>
                <Pencil className="h-4 w-4" />
                {t("editDetails")}
              </Button>
              {editable && (
                <Button
                  data-tour="datasets-add-case"
                  onClick={() => setEditing({ draft: EMPTY_DRAFT, item: null })}
                >
                  <Plus className="h-4 w-4" />
                  {t("addCase")}
                </Button>
              )}
            </>
          ) : undefined
        }
      />

      <Tabs
        defaultValue={asked !== null && TABS.includes(asked) ? asked : "cases"}
        className="space-y-4"
      >
        <TabsList>
          <TabsTrigger value="cases">{t("cases")}</TabsTrigger>
          <TabsTrigger value="scoring" data-tour="datasets-scoring-tab">
            {t("scoring.title")}
          </TabsTrigger>
          <TabsTrigger value="scores" data-tour="datasets-scores-tab">
            {t("scoring.scores")}
          </TabsTrigger>
        </TabsList>
        <TabsContent value="cases">
          <ListCard
            title={t("cases")}
            counted={t("caseCount", { count: cases.total })}
            controls={
              <div className="flex flex-wrap items-center gap-2">
                {versions.length > 0 && (
                  <VersionSelect
                    versions={versions}
                    latest={dataset.latest_version}
                    value={version}
                    onChange={(next) => {
                      setVersion(next);
                      setPage(0);
                    }}
                  />
                )}
                <DatasetFileActions
                  datasetId={id}
                  version={version}
                  onImport={editable ? (file) => cases.importFile.mutateAsync(file) : undefined}
                />
              </div>
            }
          >
            {cases.isLoading ? (
              <LoadingState variant="skeleton-cards" rows={2} />
            ) : cases.error ? (
              <ErrorState
                description={getErrorMessage(cases.error, tErrors)}
                cta={{ label: tc("retry"), onClick: () => void cases.refetch() }}
              />
            ) : cases.cases.length === 0 ? (
              <ListCardEmpty
                icon={FlaskConical}
                title={t("noCases")}
                description={t("noCasesBody")}
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
        <TabsContent value="scoring">
          <ScoringPanel
            key={JSON.stringify(dataset.scoring)}
            datasetId={id}
            scoring={dataset.scoring}
            canEdit={dataset.can_edit}
          />
        </TabsContent>
        <TabsContent value="scores">
          <ScoresPanel datasetId={id} canDecide={dataset.can_edit} />
        </TabsContent>
      </Tabs>

      <SharingPanel resourceType="dataset" resourceId={id} canManage={dataset.can_edit} />

      {editingDetails && (
        <EditDatasetDialog dataset={dataset} onOpenChange={setEditingDetails} update={update} />
      )}

      {editing !== null && (
        <CaseEditorDialog
          key={editing.item?.id ?? "new"}
          open
          onOpenChange={(open) => {
            if (!open) setEditing(null);
          }}
          initial={editing.draft}
          title={editing.item === null ? t("addCase") : t("case")}
          onSave={editable ? save : undefined}
        />
      )}
    </div>
  );
}
