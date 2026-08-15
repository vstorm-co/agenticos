"use client";

import Link from "next/link";
import { Bot, ListFilter, ShieldCheck, UserPlus } from "lucide-react";
import { useTranslations } from "next-intl";

import {
  Button,
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuTrigger,
} from "@/components/ui";
import { PeriodControl } from "@/components/dashboard/period-control";
import { useApprovals, usePermissions } from "@/hooks";
import { useOrgStore } from "@/stores";
import { ROUTES } from "@/lib/constants";
import type { SectionDef } from "@/lib/dashboard/layouts";
import type { Period } from "@/lib/dashboard/period";
import { filterableSectionIds } from "@/lib/dashboard/sections";
import { Perm } from "@/types/permissions";

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
      <PeriodControl period={period} onChange={onPeriodChange} />

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

      {/* Shortcuts, drawn as shortcuts. Four buttons of near-equal weight is
          four decisions asked at once, so the page's one primary action - go
          and talk to an agent - sits in the header where every other page in
          the product puts its primary, and what is left here is quiet. */}
      <div className="ml-auto flex flex-wrap items-center gap-1">
        {can(Perm.agentsEdit) ? (
          <Button asChild variant="ghost" size="sm" className="gap-1.5">
            <Link href={ROUTES.AGENTS}>
              <Bot className="size-3.5" aria-hidden />
              {t("actions.createAgent")}
            </Link>
          </Button>
        ) : null}
        {can(Perm.approvalsDecide) ? <ReviewApprovalsAction /> : null}
        {can(Perm.membersManage) && activeOrgId ? (
          <Button asChild variant="ghost" size="sm" className="gap-1.5">
            <Link href={ROUTES.ORG_MEMBERS(activeOrgId)}>
              <UserPlus className="size-3.5" aria-hidden />
              {t("actions.invite")}
            </Link>
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
    <Button asChild variant="ghost" size="sm" className="gap-1.5">
      <Link href={ROUTES.RUNS}>
        <ShieldCheck className="size-3.5" aria-hidden />
        {t("actions.reviewApprovals")}
        {total > 0 ? (
          <span className="bg-warning/15 text-warning ml-0.5 rounded-full px-1.5 text-[10px] font-semibold tabular-nums">
            {total}
          </span>
        ) : null}
      </Link>
    </Button>
  );
}
