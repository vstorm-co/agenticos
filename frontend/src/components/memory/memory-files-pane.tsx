"use client";

import { useState } from "react";
import { FileText, Info, Plus } from "lucide-react";

import {
  Alert,
  AlertDescription,
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
import { ErrorState, LoadingState } from "@/components/states";
import { Chip } from "@/components/memory/memory-chip";
import { CreateMemoryFileDialog } from "@/components/memory/create-memory-file-dialog";
import { MemoryFileEditor } from "@/components/memory/memory-file-editor";
import { MemoryFileTable } from "@/components/memory/memory-file-table";
import {
  useMemoryFile,
  useMemoryFiles,
  type MemoryEdit,
  type MemorySort,
} from "@/hooks/use-memory";
import { getErrorMessage } from "@/lib/api-error";
import { cn } from "@/lib/utils";
import { DIALOG_BROAD, DIALOG_FILL } from "@/lib/dialog-sizes";
import type { MemoryFileSummary } from "@/types/memory";
import { useTranslations } from "next-intl";

interface MemoryFilesPaneProps {
  agentId: string;
  canEdit: boolean;
  /** The partition the whole Memory tab is filtered to; owned by the panel.
   * `all`/`shared`/`per_user`, or a specific `user:<id>` key. */
  scope: string;
}

/**
 * The files half of the Memory tab: the agent's `MEMORY.md` index as a table an
 * operator can read, author into, edit and clear.
 *
 * The panel mounts this keyed by scope, so switching partition gives a fresh
 * page rather than paging into a partition that no longer applies.
 */
export function MemoryFilesPane({ agentId, canEdit, scope }: MemoryFilesPaneProps) {
  const t = useTranslations("memory");
  const tErrors = useTranslations("errors");
  const tc = useTranslations("common");

  const [sort, setSort] = useState<MemorySort>("name");
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(0);
  const search = useDebounced(query);

  const { files, total, isLoading, error, remove } = useMemoryFiles({
    agentId,
    scope,
    search,
    sort,
    skip: page * PAGE_SIZE,
    limit: PAGE_SIZE,
  });

  const [selected, setSelected] = useState<MemoryFileSummary | null>(null);
  const [pendingDelete, setPendingDelete] = useState<MemoryFileSummary | null>(null);
  const [createOpen, setCreateOpen] = useState(false);
  const {
    file,
    error: fileError,
    refetch: refetchFile,
    save,
    promote,
  } = useMemoryFile(agentId, selected?.id ?? null);

  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const isFiltering = search.trim() !== "";

  // Deleting the last row of a later page empties it, and the pager is hidden
  // when the page has no rows - which would strand the operator on a blank page
  // with no way back. Step to the last page that still has rows, adjusting during
  // render (React's guarded pattern) rather than in an effect (codex).
  if (page > 0 && page >= pageCount) setPage(pageCount - 1);

  function setSortReset(next: MemorySort) {
    setSort(next);
    setPage(0);
  }

  async function handleSave(edit: MemoryEdit) {
    await save.mutateAsync(edit);
    setSelected(null);
  }

  const controls = (
    <div className="flex flex-wrap items-center gap-2">
      <SearchInput
        value={query}
        onChange={(next) => {
          setQuery(next);
          setPage(0);
        }}
        placeholder={t("search")}
        className="sm:w-56"
      />
      <Button size="sm" onClick={() => setCreateOpen(true)}>
        <Plus className="h-4 w-4" />
        {t("newFile")}
      </Button>
    </div>
  );

  return (
    <>
      <Alert className="mb-4">
        <Info className="h-4 w-4" />
        <AlertDescription>{t("filesIntro")}</AlertDescription>
      </Alert>

      <ListCard
        title={t("files")}
        counted={error ? null : t("fileCount", { count: total })}
        controls={controls}
      >
        <div className="space-y-4">
          <div className="flex items-center justify-end gap-1.5">
            <span className="text-muted-foreground text-xs">{t("sort")}</span>
            <Chip active={sort === "name"} onClick={() => setSortReset("name")}>
              {t("sortName")}
            </Chip>
            <Chip active={sort === "updated"} onClick={() => setSortReset("updated")}>
              {t("sortUpdated")}
            </Chip>
          </div>

          <MemoryFileTable
            files={files}
            canEdit={canEdit}
            loading={isLoading}
            error={error ? getErrorMessage(error, tErrors) : undefined}
            activeId={selected?.id ?? null}
            onOpen={setSelected}
            onDelete={setPendingDelete}
            empty={
              <ListCardEmpty
                icon={FileText}
                title={isFiltering ? t("noMatches") : t("noFilesYet")}
                description={
                  isFiltering
                    ? t("noMatchesHint")
                    : canEdit
                      ? t("noFilesHint")
                      : t("noFilesHintViewer")
                }
              />
            }
          />

          {files.length > 0 && (
            <>
              <p className="text-muted-foreground text-xs">{t("trustHint")}</p>
              <Pager
                page={page}
                pageCount={pageCount}
                matched={total}
                total={total}
                onPage={setPage}
                counted={t("fileCount", { count: total })}
              />
            </>
          )}
        </div>
      </ListCard>

      <Dialog open={selected !== null} onOpenChange={() => setSelected(null)}>
        {selected !== null && (
          <DialogContent className={cn(DIALOG_FILL, DIALOG_BROAD)}>
            <DialogHeader>
              <DialogTitle className="font-mono">{selected.name}</DialogTitle>
              <DialogDescription>{t("editHint")}</DialogDescription>
            </DialogHeader>
            {file === undefined ? (
              fileError ? (
                <ErrorState
                  description={getErrorMessage(fileError, tErrors)}
                  cta={{ label: tc("retry"), onClick: () => void refetchFile() }}
                />
              ) : (
                <LoadingState variant="skeleton-panel" rows={2} />
              )
            ) : (
              <MemoryFileEditor
                key={file.id}
                file={file}
                canEdit={canEdit}
                isSaving={save.isPending}
                isPromoting={promote.isPending}
                onSave={handleSave}
                onPromote={() => promote.mutate()}
                onCancel={() => setSelected(null)}
              />
            )}
          </DialogContent>
        )}
      </Dialog>

      <CreateMemoryFileDialog
        agentId={agentId}
        open={createOpen}
        onOpenChange={setCreateOpen}
        canEdit={canEdit}
      />

      {pendingDelete !== null && (
        <ConfirmDialog
          open
          onOpenChange={() => setPendingDelete(null)}
          title={tc("deleteNamedConfirm", { name: pendingDelete.name })}
          description={t("deleteFileHint")}
          confirmLabel={tc("delete")}
          destructive
          loading={remove.isPending}
          onConfirm={async () => {
            await remove.mutateAsync(pendingDelete.id);
            setPendingDelete(null);
          }}
        />
      )}
    </>
  );
}
