"use client";

import { Fragment, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";

import { FilterRow } from "@/components/dashboard/filter-row";
import { OrgDivider } from "@/components/dashboard/org-divider";
import { PageHeader } from "@/components/dashboard/page-header";
import { WIDGET_COMPONENTS } from "@/components/dashboard/widgets";
import { LoadingState } from "@/components/states";
import { useOrganizationList, usePermissions } from "@/hooks";
import { useOrgStore } from "@/stores";
import { resolveAudience, SPAN_CLASS, visibleSections } from "@/lib/dashboard/layouts";
import { formatPeriodParam, parsePeriodParam, type Period } from "@/lib/dashboard/period";
import {
  applySectionsFilter,
  formatSectionsParam,
  parseSectionsParam,
} from "@/lib/dashboard/sections";
import { WIDGETS } from "@/lib/dashboard/registry";
import { setUrlParam } from "@/lib/utils";

/**
 * The role-aware dashboard: one page whose sections, cards and even numbers
 * depend on who is looking. The layout proposes per audience, the registry's
 * gates dispose per widget - a widget the caller may not see is never
 * mounted, so its queries are never issued - and each card owns its own
 * loading, empty and error states, so one failing endpoint costs one card.
 *
 * The period and sections filters live in the URL, so a view survives a
 * reload and travels in a pasted link; neither is persisted anywhere else.
 */
export default function DashboardPage() {
  const t = useTranslations("dashboard");
  const { can, role, isAppAdmin, isLoading } = usePermissions();
  const searchParams = useSearchParams();
  const [period, setPeriod] = useState<Period>(() => parsePeriodParam(searchParams.get("period")));
  const [sectionsParam, setSectionsParam] = useState<string | null>(() =>
    searchParams.get("sections"),
  );
  const activeOrgId = useOrgStore((state) => state.activeOrgId);
  const organizations = useOrganizationList();
  const activeOrgName = useMemo(
    () => organizations.data?.find((organization) => organization.id === activeOrgId)?.name ?? null,
    [organizations.data, activeOrgId],
  );

  // can() answers false while permissions load; resolving the audience from
  // that would flash a viewer-shaped page at a steward. Hold the skeleton
  // until the answer is real - nothing below mounts, so nothing fetches.
  if (isLoading) {
    return (
      <div className="space-y-6 pb-8">
        <PageHeader title={t("title")} />
        <LoadingState variant="stats" />
      </div>
    );
  }

  const audience = resolveAudience(role, isAppAdmin);
  const visible = visibleSections(audience, can, isAppAdmin);
  const selectedSections = parseSectionsParam(sectionsParam, visible);
  const sections = applySectionsFilter(visible, selectedSections);
  const firstOrgSectionId = sections.find((section) => section.id !== "deployment")?.id;

  const changePeriod = (next: Period) => {
    setPeriod(next);
    setUrlParam("period", formatPeriodParam(next));
  };
  const changeSections = (selected: string[] | null) => {
    const value = formatSectionsParam(selected);
    setSectionsParam(value);
    setUrlParam("sections", value);
  };

  return (
    <div className="space-y-6 pb-8">
      <PageHeader title={t("title")} description={t(`subtitles.${audience}`)} />
      <FilterRow
        period={period}
        onPeriodChange={changePeriod}
        sections={visible}
        selectedSections={selectedSections}
        onSectionsChange={changeSections}
      />
      {sections.map((section) => (
        <Fragment key={section.id}>
          {audience === "app_admin" && section.id === firstOrgSectionId ? (
            <OrgDivider name={activeOrgName} />
          ) : null}
          <section className="space-y-3">
            {section.titleKey ? (
              <h2 className="text-foreground text-sm font-semibold">
                {t(`sections.${section.titleKey}`)}
              </h2>
            ) : null}
            <div className="grid grid-cols-1 gap-4 lg:grid-cols-12">
              {section.entries.map((entry, index) => {
                const Widget = WIDGET_COMPONENTS[entry.widget];
                return (
                  <div key={`${entry.widget}-${index}`} className={SPAN_CLASS[entry.span]}>
                    <Widget
                      title={t(entry.titleKey ?? `widgets.${entry.widget}.title`)}
                      period={period}
                      seeAll={WIDGETS[entry.widget].seeAll}
                    />
                  </div>
                );
              })}
            </div>
          </section>
        </Fragment>
      ))}
    </div>
  );
}
