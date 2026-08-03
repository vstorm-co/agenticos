"use client";

import { useState } from "react";
import type { ReactNode } from "react";
import { BookOpen, ChevronDown, ListFilter, Lock, Plus } from "lucide-react";

import { PageHeader } from "@/components/dashboard/page-header";
import { ProposedChanges } from "@/components/skills/proposed-changes";
import { CreateSkillDialog } from "@/components/skills/create-skill-dialog";
import { SkillCard } from "@/components/skills/skill-card";
import { SkillLibraryGallery } from "@/components/skills/skill-library-gallery";
import { SkillWorkbench } from "@/components/skills/skill-workbench";
import { categoryLabel, categorySuggestions } from "@/components/skills/category-input";
import { EmptyState, LoadingState } from "@/components/states";
import {
  Button,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  ConfirmDialog,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  PAGE_SIZE,
  Pager,
  SearchInput,
  Skeleton,
  useDebounced,
} from "@/components/ui";
import { usePermissions, useSkill, useSkills } from "@/hooks";
import type { SkillEdit, SkillSort } from "@/hooks/use-skills";
import { cn } from "@/lib/utils";
import { Perm } from "@/types/permissions";
import type { SkillSummary } from "@/types/providers";

/** How many skills are in there, in words rather than a bare digit. */
function skillCount(count: number): string {
  return count === 1 ? "1 skill" : `${count} skills`;
}

/**
 * One pressed-or-not control, used for the sort.
 *
 * The category filter used to share this shape, but it grew into a
 * multi-select menu; the sort stays a two-chip row because "pick one of two"
 * is exactly what a chip says.
 */
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
        // Ink for the chosen chip, same register as the primary button - the
        // accent stays out of filter chrome.
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
 * The list's frame, drawn whether or not there is anything in it - the same
 * always-visible container the vault uses. Same header, same border, in every
 * state: what changes is what is inside it.
 */
function SkillsCard({
  count,
  controls,
  children,
}: {
  /** `null` while the request is in flight - the header then shows a skeleton. */
  count: number | null;
  controls?: ReactNode;
  children: ReactNode;
}) {
  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0 border-b px-5 py-4">
        <div className="space-y-1">
          <CardTitle className="text-sm">Skills</CardTitle>
          <CardDescription className="text-xs">
            {/* Rendering "0 skills" before the request answers would state
                something about the organization nothing has said yet. */}
            {count === null ? <Skeleton className="h-3 w-24" /> : skillCount(count)}
          </CardDescription>
        </div>
        {controls}
      </CardHeader>
      <CardContent className="p-5">{children}</CardContent>
    </Card>
  );
}

export default function SkillsPage() {
  const [query, setQuery] = useState("");
  const [selectedCategories, setSelectedCategories] = useState<string[]>([]);
  const [sort, setSort] = useState<SkillSort>("name");
  const [page, setPage] = useState(0);
  // Debounced because the search is a request, not a filter: an organization's
  // skills are paged by the database, so the client never holds them all.
  const search = useDebounced(query);
  const { skills, total, categories, suggestedCategories, isLoading, remove } = useSkills({
    search,
    categories: selectedCategories,
    sort,
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
  const isFiltering = isSearching || selectedCategories.length > 0;

  function toggleCategory(entry: string) {
    setSelectedCategories((picked) =>
      picked.includes(entry) ? picked.filter((one) => one !== entry) : [...picked, entry],
    );
    setPage(0);
  }

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

  // The same card the page renders, with card skeletons inside it. A skeleton
  // that draws a different shape from what follows is a layout jump on load.
  if (isBusy) {
    return (
      <div className="space-y-6">
        {header}
        <SkillsCard count={null}>
          <LoadingState variant="skeleton-cards" rows={3} />
        </SkillsCard>
      </div>
    );
  }

  // Rendered even on an empty result, unlike the grid: a search or a chip that
  // matched nothing has to leave the reader something to clear.
  const controls =
    isFiltering || total > 0 ? (
      <SearchInput
        value={query}
        onChange={(next) => {
          setQuery(next);
          setPage(0);
        }}
        placeholder="Search skills…"
        className="sm:w-56"
      />
    ) : undefined;

  return (
    <div className="space-y-6">
      {header}

      {/* Above the list, because it is a decision somebody has to make and the
          list is a thing to browse. Absent entirely when nothing is waiting. */}
      <ProposedChanges canEdit={canEdit} />

      <SkillsCard count={total} controls={controls}>
        <div className="space-y-4">
          {(categories.length > 0 || isFiltering || total > 0) && (
            <div className="flex flex-wrap items-center justify-between gap-3">
              {/* A menu of checkboxes rather than a chip row: shelves are
                  additive - "devops or data" is a sensible question - and a
                  row of twenty chips is a wall where a count is a summary.
                  It appears only once somebody has categorized something -
                  a filter over one shelf filters nothing. */}
              <div className="flex flex-wrap items-center gap-1.5">
                {categories.length > 0 && (
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button variant="outline" size="sm">
                        <ListFilter className="h-4 w-4" />
                        {selectedCategories.length === 0
                          ? "All categories"
                          : selectedCategories.length === 1
                            ? categoryLabel(selectedCategories[0]!)
                            : `${selectedCategories.length} categories`}
                        <ChevronDown className="h-4 w-4 opacity-60" />
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="start">
                      {categories.map((entry) => (
                        <DropdownMenuCheckboxItem
                          key={entry}
                          checked={selectedCategories.includes(entry)}
                          onCheckedChange={() => toggleCategory(entry)}
                          // Picking several is the point; the menu staying open
                          // is what makes it a multi-select rather than a detour.
                          onSelect={(event) => event.preventDefault()}
                        >
                          {categoryLabel(entry)}
                        </DropdownMenuCheckboxItem>
                      ))}
                      {selectedCategories.length > 0 && (
                        <>
                          <DropdownMenuSeparator />
                          <DropdownMenuItem
                            onSelect={() => {
                              setSelectedCategories([]);
                              setPage(0);
                            }}
                          >
                            Clear filter
                          </DropdownMenuItem>
                        </>
                      )}
                    </DropdownMenuContent>
                  </DropdownMenu>
                )}
              </div>
              <div className="flex items-center gap-1.5">
                <span className="text-muted-foreground text-xs">Sort</span>
                <Chip
                  active={sort === "name"}
                  onClick={() => {
                    setSort("name");
                    setPage(0);
                  }}
                >
                  Name
                </Chip>
                <Chip
                  active={sort === "updated"}
                  onClick={() => {
                    setSort("updated");
                    setPage(0);
                  }}
                >
                  Recently updated
                </Chip>
              </div>
            </div>
          )}

          {skills.length === 0 ? (
            // Inline rather than an `EmptyState`: that component draws its own
            // bordered box, and inside a card it would make two frames around
            // one message.
            <div className="px-6 py-16 text-center">
              <div className="bg-muted text-muted-foreground mx-auto flex h-11 w-11 items-center justify-center rounded-xl">
                <BookOpen className="h-5 w-5" />
              </div>
              <p className="text-foreground mt-4 text-sm font-medium">
                {isFiltering ? "No skill matches" : "No skills yet"}
              </p>
              <p className="text-muted-foreground mx-auto mt-1 max-w-sm text-sm">
                {isFiltering
                  ? "Names, descriptions and the picked categories were checked. Clear the search or the filter to see everything."
                  : canEdit
                    ? "Write down something your team explains more than once, and every agent can read it."
                    : "Nobody has written a skill for this organization yet."}
              </p>
              {canEdit && !isFiltering && (
                <Button
                  variant="outline"
                  size="sm"
                  className="mt-5"
                  onClick={() => setCreateOpen(true)}
                >
                  <Plus className="h-3.5 w-3.5" />
                  New skill
                </Button>
              )}
            </div>
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
        </div>
      </SkillsCard>

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
                categorySuggestions={categorySuggestions(categories, suggestedCategories)}
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
