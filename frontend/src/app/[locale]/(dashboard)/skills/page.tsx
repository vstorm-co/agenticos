"use client";

import { useState } from "react";
import { BookOpen, Lock, Plus } from "lucide-react";

import { PageHeader } from "@/components/dashboard/page-header";
import { CreateSkillDialog } from "@/components/skills/create-skill-dialog";
import { SkillCard } from "@/components/skills/skill-card";
import { SkillLibraryGallery } from "@/components/skills/skill-library-gallery";
import { SkillWorkbench } from "@/components/skills/skill-workbench";
import { EmptyState, LoadingState } from "@/components/states";
import {
  Button,
  ConfirmDialog,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  PAGE_SIZE,
  Pager,
  SearchInput,
  useDebounced,
} from "@/components/ui";
import { usePermissions, useSkill, useSkills } from "@/hooks";
import type { SkillEdit } from "@/hooks/use-skills";
import { Perm } from "@/types/permissions";
import type { SkillSummary } from "@/types/providers";

export default function SkillsPage() {
  const [query, setQuery] = useState("");
  const [page, setPage] = useState(0);
  // Debounced because the search is a request, not a filter: an organization's
  // skills are paged by the database, so the client never holds them all.
  const search = useDebounced(query);
  const { skills, total, isLoading, remove } = useSkills({
    search,
    skip: page * PAGE_SIZE,
    limit: PAGE_SIZE,
  });
  const { can, isLoading: isLoadingPermissions } = usePermissions();

  const [selected, setSelected] = useState<SkillSummary | null>(null);
  const [pendingDelete, setPendingDelete] = useState<SkillSummary | null>(null);
  const { skill, save } = useSkill(selected?.id ?? null);

  const [createOpen, setCreateOpen] = useState(false);

  const canEdit = can(Perm.skillsEdit);
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const isSearching = search.trim() !== "";

  async function handleSave(edit: SkillEdit) {
    await save.mutateAsync(edit);
    setSelected(null);
  }

  const isBusy = isLoading || isLoadingPermissions;

  const header = (
    <PageHeader
      title="Skills"
      description="A skill is know-how written once and shared by every agent that needs it - how refunds are handled, what the house style is. Edit it here and each agent bound to it is current on its next run."
      actions={
        canEdit ? (
          <Button onClick={() => setCreateOpen(true)}>
            <Plus className="h-4 w-4" />
            New skill
          </Button>
        ) : undefined
      }
    />
  );

  // Only once permissions are known: "you cannot see these" is a verdict, and
  // showing it while the answer is still in flight accuses the reader of
  // something the server has not said yet.
  if (!isBusy && !can(Perm.skillsView)) {
    return (
      <div className="space-y-6">
        {header}
        <EmptyState
          icon={Lock}
          title="You cannot see this organization's skills"
          description="Ask an administrator for access to skills."
        />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {header}

      {/* Rendered even on an empty result, unlike the rest: a search that
          matched nothing has to leave the reader something to clear. */}
      {(isSearching || total > 0) && (
        <SearchInput
          value={query}
          onChange={(next) => {
            setQuery(next);
            setPage(0);
          }}
          placeholder="Search skills…"
        />
      )}

      {isBusy ? (
        <LoadingState variant="skeleton-cards" />
      ) : skills.length === 0 ? (
        <EmptyState
          icon={BookOpen}
          title={isSearching ? `No skill matches “${search}”` : "No skills yet"}
          description={
            isSearching
              ? "Names and descriptions are searched. Nothing here matched."
              : canEdit
                ? "Write down something your team explains more than once, and every agent can read it."
                : "Nobody has written a skill for this organization yet."
          }
          cta={
            canEdit && !isSearching
              ? { label: "New skill", onClick: () => setCreateOpen(true) }
              : undefined
          }
        />
      ) : (
        <>
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
            {skills.map((entry) => (
              <SkillCard
                key={entry.id}
                skill={entry}
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
            noun="skills"
          />
        </>
      )}

      {/* Below the organization's own, not above: what somebody already wrote
          is what they came here for. */}
      <SkillLibraryGallery canInstall={canEdit} />

      <Dialog
        open={selected !== null}
        onOpenChange={(open) => {
          if (!open) setSelected(null);
        }}
      >
        {selected !== null && (
          <DialogContent className="flex h-[92vh] flex-col sm:max-w-[92rem]">
            <DialogHeader>
              <DialogTitle className="font-mono">{selected.name}</DialogTitle>
              <DialogDescription>
                The name is how the model refers to this skill, and it cannot change. Everything
                else here can.
              </DialogDescription>
            </DialogHeader>
            {skill === undefined ? (
              <LoadingState variant="skeleton-panel" rows={2} />
            ) : (
              <SkillWorkbench
                key={skill.id}
                skill={skill}
                canEdit={canEdit}
                isSaving={save.isPending}
                onSave={handleSave}
                onCancel={() => setSelected(null)}
              />
            )}
          </DialogContent>
        )}
      </Dialog>

      <CreateSkillDialog open={createOpen} onOpenChange={setCreateOpen} />

      {pendingDelete !== null && (
        <ConfirmDialog
          open
          onOpenChange={() => setPendingDelete(null)}
          title={`Delete ${pendingDelete.name}?`}
          description="Agents bound to this skill will run without it from their next run. This cannot be undone."
          confirmLabel="Delete"
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
