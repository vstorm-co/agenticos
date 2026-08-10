"use client";

import Link from "next/link";
import { CalendarRange, ListFilter } from "lucide-react";
import { useTranslations } from "next-intl";

import {
  Button,
  DateRangePicker,
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuTrigger,
  Popover,
  PopoverContent,
  PopoverTrigger,
} from "@/components/ui";
import { useApprovals, usePermissions } from "@/hooks";
import { useOrgStore } from "@/stores";
import { ROUTES } from "@/lib/constants";
import type { SectionDef } from "@/lib/dashboard/layouts";
import {
  customPeriod,
  PERIOD_PRESETS,
  resolvePreset,
  type Period,
  type PeriodPreset,
} from "@/lib/dashboard/period";
import { filterableSectionIds } from "@/lib/dashboard/sections";
import { Perm } from "@/types/permissions";
import { cn } from "@/lib/utils";

interface FilterRowProps {
  period: Period;
  onPeriodChange: (period: Period) => void;
  /** The caller's visible sections - the filter can only ever hide. */
  sections: SectionDef[];
  selectedSections: string[] | null;
  onSectionsChange: (selected: string[] | null) => void;
}

/**
 * The page's one control strip: period presets, the custom range, the
 * sections filter, and one quick action per permission - a caller who may
 * not do a thing is not shown its button.
 */
export function FilterRow({
  period,
  onPeriodChange,
  sections,
  selectedSections,
  onSectionsChange,
}: FilterRowProps) {
  const t = useTranslations("dashboard");
  const { can } = usePermissions();
  const activeOrgId = useOrgStore((state) => state.activeOrgId);
  const filterable = filterableSectionIds(sections);

  return (
    <div className="flex flex-wrap items-center gap-2">
      <div
        className="bg-muted flex flex-wrap items-center gap-1 rounded-full p-1"
        role="group"
        aria-label={t("period.label")}
      >
        {PERIOD_PRESETS.map((preset: PeriodPreset) => (
          <button
            key={preset}
            type="button"
            aria-pressed={period.preset === preset}
            onClick={() => onPeriodChange(resolvePreset(preset))}
            className={cn(
              "rounded-full px-3 py-1 text-xs font-medium transition-colors",
              period.preset === preset
                ? "bg-card text-foreground shadow-card"
                : "text-muted-foreground hover:text-foreground",
            )}
          >
            {t(`period.${preset}`)}
          </button>
        ))}
        <Popover>
          <PopoverTrigger asChild>
            <button
              type="button"
              aria-pressed={period.preset === "custom"}
              className={cn(
                "flex items-center gap-1 rounded-full px-3 py-1 text-xs font-medium transition-colors",
                period.preset === "custom"
                  ? "bg-card text-foreground shadow-card"
                  : "text-muted-foreground hover:text-foreground",
              )}
            >
              <CalendarRange className="size-3.5" aria-hidden />
              {period.preset === "custom" ? `${period.from} – ${period.to}` : t("period.custom")}
            </button>
          </PopoverTrigger>
          <PopoverContent align="start" className="w-auto p-4">
            <DateRangePicker
              value={period.preset === "custom" ? { from: period.from, to: period.to } : null}
              onChange={(range) => onPeriodChange(customPeriod(range.from, range.to))}
            />
          </PopoverContent>
        </Popover>
      </div>

      {filterable.length > 1 ? (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button variant="outline" size="sm" className="gap-1.5">
              <ListFilter className="size-3.5" aria-hidden />
              {t("sectionsFilter.label")}
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="start">
            {sections
              .filter((section) => section.titleKey !== null)
              .map((section) => {
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
                    {t(`sections.${section.titleKey}`)}
                  </DropdownMenuCheckboxItem>
                );
              })}
          </DropdownMenuContent>
        </DropdownMenu>
      ) : null}

      <div className="ml-auto flex flex-wrap items-center gap-2">
        {can(Perm.agentsRun) ? (
          <Button asChild size="sm">
            <Link href={ROUTES.CHAT}>{t("actions.newChat")}</Link>
          </Button>
        ) : null}
        {can(Perm.agentsEdit) ? (
          <Button asChild variant="outline" size="sm">
            <Link href={ROUTES.AGENTS}>{t("actions.createAgent")}</Link>
          </Button>
        ) : null}
        {can(Perm.approvalsDecide) ? <ReviewApprovalsAction /> : null}
        {can(Perm.membersManage) && activeOrgId ? (
          <Button asChild variant="outline" size="sm">
            <Link href={ROUTES.ORG_MEMBERS(activeOrgId)}>{t("actions.invite")}</Link>
          </Button>
        ) : null}
      </div>
    </div>
  );
}

/**
 * Its own component so the approvals query is only ever issued by a caller
 * holding approvals:decide - a hook cannot sit behind an `if`.
 */
function ReviewApprovalsAction() {
  const t = useTranslations("dashboard");
  const { total } = useApprovals();

  return (
    <Button asChild variant="outline" size="sm">
      <Link href={ROUTES.RUNS}>
        {t("actions.reviewApprovals")}
        {total > 0 ? (
          <span className="bg-warning/15 text-warning ml-1.5 rounded-full px-1.5 text-[10px] font-semibold tabular-nums">
            {total}
          </span>
        ) : null}
      </Link>
    </Button>
  );
}
