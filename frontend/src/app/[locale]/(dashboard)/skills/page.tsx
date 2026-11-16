"use client";

import { FILTER_CONTROL } from "@/components/ui/control-styles";

import { useState } from "react";
import type { ReactNode } from "react";
import { BookOpen, ChevronDown, Library, ListFilter, Lock, Plus } from "lucide-react";

import { ListFilters } from "@/components/ui/list-filters";
import { PageHeader } from "@/components/dashboard/page-header";
import { ProposedChanges } from "@/components/skills/proposed-changes";
import { CreateSkillDialog } from "@/components/skills/create-skill-dialog";
import { SkillGalleryDialog } from "@/components/skills/skill-gallery-dialog";
import { SkillDetailDialog } from "@/components/skills/skill-detail-dialog";
import { SkillCard } from "@/components/skills/skill-card";
import { categoryLabel } from "@/components/skills/category-input";
import { CatalogLoading } from "@/components/states/catalog-loading";
import { EmptyState, ErrorState } from "@/components/states";
import {
  Button,
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
  ListCard,
  ListCardEmpty,
  PAGE_SIZE,
  Pager,
  SearchInput,
  useDebounced,
} from "@/components/ui";
import { GroupFilter, NothingSharedWithGroup } from "@/components/groups/group-filter";
import { usePermissions, useSkills, useUrlState } from "@/hooks";
import { useUrlOverlay } from "@/hooks/use-url-state";
import type { SkillSort } from "@/hooks/use-skills";
import { getErrorMessage } from "@/lib/api-error";
import { cn } from "@/lib/utils";
import { Perm } from "@/types/permissions";
import { useTranslations } from "next-intl";

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
        "touch:min-h-11 touch-manipulation rounded-full border px-2.5 py-1 text-xs font-medium transition-colors",
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

export default function SkillsPage() {
  const [selectedSkill, skillView] = useUrlOverlay("skill");
  const t = useTranslations("pages.skills");
  const tc = useTranslations("common");
  const tErrors = useTranslations("errors");
  const [query, setQuery] = useState("");
  const [selectedCategories, setSelectedCategories] = useState<string[]>([]);
  const [sort, setSort] = useState<SkillSort>("name");
  const [page, setPage] = useState(0);
  // Debounced because the search is a request, not a filter: an organization's
  // skills are paged by the database, so the client never holds them all.
  const search = useDebounced(query);
  // In the address, so a group's skills are a link somebody can send.
  const [groupId, setGroupId] = useUrlState("group");
  const { skills, total, categories, isLoading, error, refetch } = useSkills({
    search,
    categories: selectedCategories,
    sort,
    skip: page * PAGE_SIZE,
    limit: PAGE_SIZE,
    groupId,
  });
  const { can, isLoading: isLoadingPermissions } = usePermissions();

  const [createOpen, setCreateOpen] = useState(false);
  const [galleryOpen, setGalleryOpen] = useState(false);
  const tGallery = useTranslations("skills.gallery");

  const canCreate = can(Perm.skillsEdit);
  const pageCount = Math.max(1, Math.ceil(total / PAGE_SIZE));
  const isSearching = search.trim() !== "";
  const isFiltering = isSearching || selectedCategories.length > 0 || groupId !== null;

  function toggleCategory(entry: string) {
    setSelectedCategories((picked) =>
      picked.includes(entry) ? picked.filter((one) => one !== entry) : [...picked, entry],
    );
    setPage(0);
  }

  const isBusy = isLoading || isLoadingPermissions;

  const header = (
    <PageHeader
      title={t("skills2")}
      description={t("skillKnowHowWritten")}
      secondaryActions={
        canCreate ? (
          <Button variant="outline" data-tour="skills-gallery" onClick={() => setGalleryOpen(true)}>
            <Library className="h-4 w-4" />
            {tGallery("browse")}
          </Button>
        ) : undefined
      }
      actions={
        canCreate ? (
          <Button data-tour="skills-new" onClick={() => setCreateOpen(true)}>
            <Plus className="h-4 w-4" />
            {t("newSkill")}
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
      <div className="flex flex-1 flex-col space-y-4">
        {header}
        <EmptyState
          icon={Lock}
          title={t("youCannotSeeOrganization")}
          description={t("askAdministratorAccessSkills")}
        />
      </div>
    );
  }

  // The same card the page renders, with card skeletons inside it. A skeleton
  // that draws a different shape from what follows is a layout jump on load.
  if (isBusy) {
    return (
      <div className="flex flex-1 flex-col space-y-4">
        {header}
        <ListCard fill namedByPage title={t("skills")} counted={null}>
          <CatalogLoading kind="document" />
        </ListCard>
      </div>
    );
  }

  // Rendered even on an empty result, unlike the grid: a search or a chip that
  // matched nothing has to leave the reader something to clear.
  const controls =
    isFiltering || total > 0 || categories.length > 0 ? (
      <div className="flex min-w-0 flex-wrap items-center gap-2">
        <SearchInput
          value={query}
          onChange={(next) => {
            setQuery(next);
            setPage(0);
          }}
          placeholder={t("searchSkills")}
          className="min-w-0 flex-1 sm:w-56 sm:flex-none"
        />
        <ListFilters
          compact
          active={selectedCategories.length + Number(groupId !== null) + Number(sort !== "name")}
        >
          <div className="flex w-full flex-col gap-3 sm:w-auto sm:flex-row sm:flex-wrap sm:items-center sm:justify-between">
            {/* A menu of checkboxes rather than a chip row: shelves are
                  additive - "devops or data" is a sensible question - and a
                  row of twenty chips is a wall where a count is a summary.
                  It appears only once somebody has categorized something -
                  a filter over one shelf filters nothing. */}
            <div className="grid w-full grid-cols-1 gap-2 sm:flex sm:w-auto sm:flex-wrap sm:items-center max-sm:[&>button]:w-full max-sm:[&>button]:justify-between">
              {categories.length > 0 && (
                <DropdownMenu>
                  <DropdownMenuTrigger asChild>
                    {/* Drawn like every other filter in the console - the
                          agents' label filters and the selects beside them. */}
                    <Button variant="outline" className={FILTER_CONTROL}>
                      <ListFilter
                        className="size-3.5 shrink-0 opacity-70"
                        strokeWidth={1.75}
                        aria-hidden
                      />
                      {selectedCategories.length === 0
                        ? t("allCategories")
                        : selectedCategories.length === 1
                          ? categoryLabel(selectedCategories[0]!)
                          : t("categoryCount", { count: selectedCategories.length })}
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
                          {t("clearFilter")}
                        </DropdownMenuItem>
                      </>
                    )}
                  </DropdownMenuContent>
                </DropdownMenu>
              )}
              <GroupFilter
                value={groupId}
                onChange={(next) => {
                  setGroupId(next);
                  setPage(0);
                }}
              />
            </div>
            <div className="flex flex-wrap items-center gap-1.5">
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
          </div>
        </ListFilters>
      </div>
    ) : undefined;

  return (
    <div className="flex flex-1 flex-col space-y-4">
      {header}

      {/* Above the list, because it is a decision somebody has to make and the
          list is a thing to browse. Absent entirely when nothing is waiting. */}
      <ProposedChanges canEdit={canCreate} />

      <ListCard
        fill
        data-tour="skills-list"
        namedByPage
        title={t("skills")}
        // The count is a claim about the organization, and a failed request has
        // made none - so an error draws the skeleton, not "0 skills".
        counted={error ? null : t("skillCount", { count: total })}
        controls={controls}
        empty={!error && !isFiltering && total === 0 && categories.length === 0}
      >
        <div className="space-y-4">
          {error ? (
            // Not the empty state: "no skills yet" and "the request failed" are
            // different facts, and only one of them offers a create button.
            <ErrorState
              description={getErrorMessage(error, tErrors)}
              cta={{ label: tc("retry"), onClick: () => void refetch() }}
            />
          ) : skills.length === 0 &&
            groupId !== null &&
            !isSearching &&
            selectedCategories.length === 0 ? (
            <NothingSharedWithGroup groupId={groupId} />
          ) : skills.length === 0 ? (
            <ListCardEmpty
              icon={BookOpen}
              title={isFiltering ? t("noSkillMatches") : t("noSkillsYet")}
              description={
                isFiltering
                  ? t("namesDescriptionsPickedCategories")
                  : canCreate
                    ? t("writeDownSomethingYour")
                    : t("nobodyHasWrittenSkill")
              }
              cta={
                canCreate && !isFiltering
                  ? {
                      label: (
                        <>
                          <Plus className="h-3.5 w-3.5" />
                          {t("newSkill2")}
                        </>
                      ),
                      onClick: () => setCreateOpen(true),
                    }
                  : undefined
              }
            />
          ) : (
            <>
              <div className="rise-in grid grid-cols-1 items-stretch gap-3 md:grid-cols-2 xl:grid-cols-3">
                {skills.map((entry) => (
                  <SkillCard key={entry.id} skill={entry} onOpen={() => skillView.open(entry.id)} />
                ))}
              </div>
              <Pager
                page={page}
                pageCount={pageCount}
                matched={total}
                total={total}
                onPage={setPage}
                counted={t("skillCount", { count: total })}
              />
            </>
          )}
        </div>
      </ListCard>

      {selectedSkill !== null && (
        <SkillDetailDialog
          id={selectedSkill}
          name={skills.find((skill) => skill.id === selectedSkill)?.name}
          canEdit={skills.find((skill) => skill.id === selectedSkill)?.can_edit}
          onClose={skillView.close}
        />
      )}
      <CreateSkillDialog open={createOpen} onOpenChange={setCreateOpen} />
      <SkillGalleryDialog open={galleryOpen} onOpenChange={setGalleryOpen} />
    </div>
  );
}
