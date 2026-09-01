"use client";

import { useState } from "react";
import type { ReactNode } from "react";
import { FileText, Plus } from "lucide-react";

import {
  Badge,
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
import { LoadingState } from "@/components/states";
import { CreateMemoryFileDialog } from "@/components/memory/create-memory-file-dialog";
import { MemoryFileEditor } from "@/components/memory/memory-file-editor";
import { MemoryFileTable } from "@/components/memory/memory-file-table";
import {
  useMemoryFile,
  useMemoryFiles,
  type MemoryEdit,
  type MemoryScope,
  type MemorySort,
} from "@/hooks/use-memory";
import { getErrorMessage } from "@/lib/api-error";
import { cn } from "@/lib/utils";
import { DIALOG_BROAD, DIALOG_FILL } from "@/lib/dialog-sizes";
import type { MemoryFileSummary } from "@/types/memory";
import { useTranslations } from "next-intl";

interface MemoryPanelProps {
  agentId: string;
  canEdit: boolean;
  /** How the capability is configured, for the two header badges. */
  partition: "shared" | "per_user";
  backend: "native" | "mem0";
}

/** One pressed-or-not filter control. */
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

/**
 * The Memory tab's file manager: the agent's `MEMORY.md` index as a table an
 * operator can read, author into and clear from.
 *
 * The scope control filters the partition (the shared store, or every partition
 * at once), and the sort matches the server's two orders. The bodies are never
 * in the list — a row opens the editor, which fetches one.
 */
export function MemoryPanel({ agentId, canEdit, partition, backend }: MemoryPanelProps) {
  const t = useTranslations("memory");
  const tErrors = useTranslations("errors");
  const tc = useTranslations("common");

  const [scope, setScope] = useState<MemoryScope>("all");
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
  const { file, save, promote } = useMemoryFile(agentId, selected?.id ?? null);

  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const isFiltering = search.trim() !== "";

  function resetPage<T>(set: (value: T) => void) {
    return (value: T) => {
      set(value);
      setPage(0);
    };
  }

  async function handleSave(edit: MemoryEdit) {
    await save.mutateAsync(edit);
    setSelected(null);
  }

  const controls = (
    <div className="flex flex-wrap items-center gap-2">
      <SearchInput
        value={query}
        onChange={resetPage(setQuery)}
        placeholder={t("search")}
        className="sm:w-56"
      />
      {canEdit && (
        <Button size="sm" data-tour="agent-memory-new" onClick={() => setCreateOpen(true)}>
          <Plus className="h-4 w-4" />
          {t("newFile")}
        </Button>
      )}
    </div>
  );

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center gap-2">
        <Badge variant="secondary">
          {t(partition === "per_user" ? "cfgPerUser" : "cfgShared")}
        </Badge>
        <Badge variant="outline">{t(backend === "mem0" ? "cfgMem0" : "cfgNative")}</Badge>
      </div>

      <ListCard
        title={t("files")}
        counted={error ? null : t("fileCount", { count: total })}
        controls={controls}
      >
        <div className="space-y-4">
          <div className="flex flex-wrap items-center justify-between gap-2">
            <div className="flex items-center gap-1.5">
              <span className="text-muted-foreground text-xs">{t("scope")}</span>
              <Chip active={scope === "all"} onClick={() => resetPage(setScope)("all")}>
                {t("scopeAll")}
              </Chip>
              <Chip active={scope === "shared"} onClick={() => resetPage(setScope)("shared")}>
                {t("scopeShared")}
              </Chip>
            </div>
            <div className="flex items-center gap-1.5">
              <span className="text-muted-foreground text-xs">{t("sort")}</span>
              <Chip active={sort === "name"} onClick={() => resetPage(setSort)("name")}>
                {t("sortName")}
              </Chip>
              <Chip active={sort === "updated"} onClick={() => resetPage(setSort)("updated")}>
                {t("sortUpdated")}
              </Chip>
            </div>
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
              <LoadingState variant="skeleton-panel" rows={2} />
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

      <CreateMemoryFileDialog agentId={agentId} open={createOpen} onOpenChange={setCreateOpen} />

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
    </div>
  );
}
