"use client";

import { ListFilter } from "lucide-react";
import { useTranslations } from "next-intl";

import {
  Button,
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from "@/components/ui";
import { PeriodControl } from "@/components/dashboard/period-control";
import type { SectionDef } from "@/lib/dashboard/layouts";
import type { Period } from "@/lib/dashboard/period";
import { filterableSectionIds, isFilterable, sectionLabel } from "@/lib/dashboard/sections";

interface FilterRowProps {
  period: Period;
  onPeriodChange: (period: Period) => void;
  /** The caller's visible sections - the filter can only ever hide. */
  sections: SectionDef[];
  selectedSections: string[] | null;
  onSectionsChange: (selected: string[] | null) => void;
}

/**
 * The page's controls: which window, and which sections. Two quiet buttons -
 * the shortcuts that sat beside them (create an agent, review approvals,
 * invite) and the seven-choice period strip made the page a toolbar before it
 * was a dashboard.
 */
export function FilterRow({
  period,
  onPeriodChange,
  sections,
  selectedSections,
  onSectionsChange,
}: FilterRowProps) {
  const t = useTranslations("dashboard");
  const filterable = filterableSectionIds(sections);

  return (
    <div className="flex flex-wrap items-center gap-2">
      <div data-tour="dashboard-filters" className="flex flex-wrap items-center gap-2">
        <PeriodControl period={period} onChange={onPeriodChange} variant="menu" />

        {filterable.length > 1 ? (
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline" size="sm" className="gap-1.5">
                <ListFilter className="size-3.5" aria-hidden />
                {t("sectionsFilter.label")}
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="start">
              {sections.filter(isFilterable).map((section) => {
                const checked = selectedSections === null || selectedSections.includes(section.id);
                return (
                  <DropdownMenuCheckboxItem
                    key={section.id}
                    checked={checked}
                    onCheckedChange={(next) => {
                      const current =
                        selectedSections === null ? [...filterable] : [...selectedSections];
                      const updated = next
                        ? [...current, section.id]
                        : current.filter((id) => id !== section.id);
                      // Deselecting everything means "no filter", never an
                      // empty page - same rule the URL parser applies.
                      onSectionsChange(
                        updated.length === 0 || updated.length === filterable.length
                          ? null
                          : updated,
                      );
                    }}
                  >
                    {sectionLabel(section, t)}
                  </DropdownMenuCheckboxItem>
                );
              })}
            </DropdownMenuContent>
          </DropdownMenu>
        ) : null}
      </div>
    </div>
  );
}
