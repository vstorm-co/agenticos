"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { CatalogLoading } from "@/components/states/catalog-loading";
import { ErrorState } from "@/components/states";
import { PAGE_SIZE, Pager } from "@/components/ui";
import { useSkills, type SkillSort } from "@/hooks/use-skills";
import { getErrorMessage } from "@/lib/api-error";
import { SkillGrid } from "./skill-grid";

/** The listing's filters, which a section's pages keep. */
export interface SectionFilters {
  search: string;
  categories: string[];
  sort: SkillSort;
  groupId: string | null;
}

/**
 * Every skill in one section, paged like the plain grid.
 *
 * The same listing under the same filters, narrowed to the section by its key,
 * so the pages add up to the count the section's heading showed.
 */
export function SkillSectionPages({
  sectionKey,
  filters,
  onOpen,
}: {
  sectionKey: string;
  filters: SectionFilters;
  onOpen: (id: string) => void;
}) {
  const t = useTranslations("pages.skills");
  const tc = useTranslations("common");
  const tErrors = useTranslations("errors");
  const [page, setPage] = useState(0);
  const { skills, total, isLoading, error, refetch } = useSkills({
    ...filters,
    section: sectionKey,
    skip: page * PAGE_SIZE,
    limit: PAGE_SIZE,
  });

  if (isLoading) return <CatalogLoading kind="document" />;
  if (error) {
    return (
      <ErrorState
        description={getErrorMessage(error, tErrors)}
        cta={{ label: tc("retry"), onClick: () => void refetch() }}
      />
    );
  }
  return (
    <>
      <SkillGrid skills={skills} onOpen={onOpen} />
      <Pager
        page={page}
        pageCount={Math.max(1, Math.ceil(total / PAGE_SIZE))}
        matched={total}
        total={total}
        onPage={setPage}
        counted={t("skillCount", { count: total })}
      />
    </>
  );
}
