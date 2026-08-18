"use client";

import { useState } from "react";
import type { ReactNode } from "react";
import { FileText, Lock, Plus } from "lucide-react";

import { PageHeader } from "@/components/dashboard/page-header";
import { ContextCard } from "@/components/context/context-card";
import { ContextEditor } from "@/components/context/context-editor";
import { CreateContextDialog } from "@/components/context/create-context-dialog";
import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import {
  Button,
  ConfirmDialog,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  ListCard,
  ListCardEmpty,
  PAGE_SIZE,
  Pager,
  SearchInput,
  useDebounced,
} from "@/components/ui";
import { usePermissions } from "@/hooks";
import { useContextFile, useContextFiles } from "@/hooks/use-context";
import type { ContextEdit, ContextSort } from "@/hooks/use-context";
import { getErrorMessage } from "@/lib/api-error";
import { cn } from "@/lib/utils";
import { Perm } from "@/types/permissions";
import type { ContextFileSummary } from "@/types/providers";
import { useTranslations } from "next-intl";

/** One pressed-or-not sort control. */
function Chip({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: ReactNode;
}) {
  return (
    <button
      type="button"
      aria-pressed={active}
      onClick={onClick}
      className={cn(
        "rounded-full border px-2.5 py-1 text-xs font-medium transition-colors",
        active
          ? "bg-primary text-primary-foreground border-transparent"
          : "text-muted-foreground hover:bg-accent hover:text-foreground border-border",
      )}
    >
      {children}
    </button>
  );
}

export default function ContextPage() {
  const t = useTranslations("pages.context");
  const tc = useTranslations("common");
  const tErrors = useTranslations("errors");
  const [query, setQuery] = useState("");
  const [sort, setSort] = useState<ContextSort>("name");
  const [page, setPage] = useState(0);
  const search = useDebounced(query);
  const { files, total, isLoading, error, refetch, remove } = useContextFiles({
    search,
    sort,
    skip: page * PAGE_SIZE,
    limit: PAGE_SIZE,
  });
  const { can, isLoading: isLoadingPermissions } = usePermissions();

  const [selected, setSelected] = useState<ContextFileSummary | null>(null);
  const [pendingDelete, setPendingDelete] = useState<ContextFileSummary | null>(null);
  const { file, save } = useContextFile(selected?.id ?? null);
  const [createOpen, setCreateOpen] = useState(false);

  const canEdit = can(Perm.contextEdit);
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const isFiltering = search.trim() !== "";

  async function handleSave(edit: ContextEdit) {
    await save.mutateAsync(edit);
    setSelected(null);
  }

  const isBusy = isLoading || isLoadingPermissions;

  const header = (
    <PageHeader
      title={t("context")}
      description={t("contextStandingKnowledge")}
      actions={
        canEdit ? (
          <Button data-tour="context-new" onClick={() => setCreateOpen(true)}>
            <Plus className="h-4 w-4" />
            {t("newContext")}
          </Button>
        ) : undefined
      }
    />
  );

  if (!isBusy && !can(Perm.contextView)) {
    return (
      <div className="space-y-6">
        {header}
        <EmptyState
          icon={Lock}
          title={t("youCannotSeeOrganization")}
          description={t("askAdministratorAccessContext")}
        />
      </div>
    );
  }

  if (isBusy) {
    return (
      <div className="space-y-6">
        {header}
        <ListCard title={t("contextFiles")} counted={null}>
          <LoadingState variant="skeleton-cards" rows={3} />
        </ListCard>
      </div>
    );
  }

  const controls =
    isFiltering || total > 0 ? (
      <SearchInput
        value={query}
        onChange={(next) => {
          setQuery(next);
          setPage(0);
        }}
        placeholder={t("searchContext")}
        className="sm:w-56"
      />
    ) : undefined;

  return (
    <div className="space-y-6">
      {header}

      <ListCard
        data-tour="context-list"
        title={t("contextFiles")}
        counted={error ? null : t("contextCount", { count: total })}
        controls={controls}
      >
        <div className="space-y-4">
          {total > 0 && (
            <div className="flex items-center justify-end gap-1.5">
              <span className="text-muted-foreground text-xs">{t("sort")}</span>
              <Chip
                active={sort === "name"}
                onClick={() => {
                  setSort("name");
                  setPage(0);
                }}
              >
                {t("name")}
              </Chip>
              <Chip
                active={sort === "updated"}
                onClick={() => {
                  setSort("updated");
                  setPage(0);
                }}
              >
                {t("recentlyUpdated")}
              </Chip>
            </div>
          )}

          {error ? (
            <ErrorState
              description={getErrorMessage(error, tErrors)}
              cta={{ label: tc("retry"), onClick: () => void refetch() }}
            />
          ) : files.length === 0 ? (
            <ListCardEmpty
              icon={FileText}
              title={isFiltering ? t("noContextMatches") : t("noContextYet")}
              description={
                isFiltering
                  ? t("namesDescriptionsSearched")
                  : canEdit
                    ? t("addSomethingYourAgents")
                    : t("nobodyHasAddedContext")
              }
              cta={
                canEdit && !isFiltering
                  ? {
                      label: (
                        <>
                          <Plus className="h-3.5 w-3.5" />
                          {t("newContext2")}
                        </>
                      ),
                      onClick: () => setCreateOpen(true),
                    }
                  : undefined
              }
            />
          ) : (
            <>
              <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
                {files.map((entry) => (
                  <ContextCard
                    key={entry.id}
                    file={entry}
                    canEdit={canEdit}
                    onOpen={() => setSelected(entry)}
                    onDelete={() => setPendingDelete(entry)}
                  />
                ))}
              </div>
              <Pager
                page={page}
                pageCount={pageCount}
                matched={total}
                total={total}
                onPage={setPage}
                counted={t("contextCount", { count: total })}
              />
            </>
          )}
        </div>
      </ListCard>

      <Dialog
        open={selected !== null}
        onOpenChange={(open) => {
          if (!open) setSelected(null);
        }}
      >
        {selected !== null && (
          <DialogContent className="flex h-[92vh] flex-col sm:max-w-4xl">
            <DialogHeader>
              <DialogTitle className="font-mono">{selected.name}</DialogTitle>
              <DialogDescription>{t("nameHowItIsReferred")}</DialogDescription>
            </DialogHeader>
            {file === undefined ? (
              <LoadingState variant="skeleton-panel" rows={2} />
            ) : (
              <ContextEditor
                key={file.id}
                file={file}
                canEdit={canEdit}
                isSaving={save.isPending}
                onSave={handleSave}
                onCancel={() => setSelected(null)}
              />
            )}
          </DialogContent>
        )}
      </Dialog>

      <CreateContextDialog open={createOpen} onOpenChange={setCreateOpen} />

      {pendingDelete !== null && (
        <ConfirmDialog
          open
          onOpenChange={() => setPendingDelete(null)}
          title={tc("deleteNamedConfirm", { name: pendingDelete.name })}
          description={t("agentsBoundContextWill")}
          confirmLabel={t("delete")}
          destructive
          loading={remove.isPending}
          onConfirm={async () => {
            await remove.mutateAsync(pendingDelete.id);
            setPendingDelete(null);
          }}
        />
      )}
    </div>
  );
}
