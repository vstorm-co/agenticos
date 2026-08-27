"use client";

import { type CSSProperties, Fragment, useMemo, useState } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { ChevronDown, ChevronRight, LayoutGrid, MessageSquarePlus } from "lucide-react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { DashboardEditor } from "@/components/dashboard/dashboard-editor";
import { DashboardPresetMenu } from "@/components/dashboard/dashboard-preset-menu";
import { FilterRow } from "@/components/dashboard/filter-row";
import { OrgDivider } from "@/components/dashboard/org-divider";
import { PageHeader } from "@/components/dashboard/page-header";
import { WIDGET_COMPONENTS } from "@/components/dashboard/widgets";
import { Button } from "@/components/ui";
import { EmptyState, LoadingState } from "@/components/states";
import {
  useDashboardLayout,
  useDashboardPresets,
  useOrganizationList,
  usePermissions,
} from "@/hooks";
import type { DashboardPreset } from "@/lib/dashboard-preset-api";
import { useOrgStore } from "@/stores";
import {
  ARRANGED_GRID_CLASS,
  resolveAudience,
  ROW_CLASS,
  SPAN_CLASS,
  visibleSections,
  type SectionDef,
} from "@/lib/dashboard/layouts";
import {
  flattenDefaultToItems,
  resolveEffectiveLayout,
  sanitizeEntries,
  toStored,
  visibleItems,
  widgetCatalog,
  type StoredEntry,
} from "@/lib/dashboard/preference";
import {
  formatPeriodParam,
  parsePeriodParam,
  resolvePreset,
  type Period,
} from "@/lib/dashboard/period";
import { BAND_GAP, HEADING_GAP } from "@/lib/dashboard/system";
import {
  applySectionsFilter,
  formatSectionsParam,
  parseSectionsParam,
  sectionLabel,
} from "@/lib/dashboard/sections";
import { accentDecoration, isAccentColour, WIDGETS } from "@/lib/dashboard/registry";
import { ROUTES } from "@/lib/constants";
import { cn, setUrlParam } from "@/lib/utils";
import { Perm } from "@/types/permissions";

/**
 * The role-aware dashboard, now arrangeable. Three layers decide what renders,
 * in this order and no other:
 *
 *   effective = stored preference ?? audience default   (resolveEffectiveLayout)
 *   visible   = visibleSections(effective, can, isAppAdmin)   // the gate, last
 *
 * A person can reorder, hide, resize or add cards; the gate still runs last on
 * whatever they saved, so a preference can never reveal a widget they may not
 * see - a demotion drops it at render time rather than trusting the stored
 * layout. Nothing about a saved layout is trusted on read: an unknown widget id
 * is dropped and an unknown span falls back, both before the gate.
 *
 * The period and sections filters live in the URL; the arrangement is the one
 * thing persisted, per user and per organization.
 */
export default function DashboardPage() {
  const t = useTranslations("dashboard");
  const { can, role, isAppAdmin, isLoading } = usePermissions();
  const { storedEntries, save, reset } = useDashboardLayout();
  const { presets, savePreset, removePreset } = useDashboardPresets();
  const searchParams = useSearchParams();
  const [period, setPeriod] = useState<Period>(() => parsePeriodParam(searchParams.get("period")));
  const [sectionsParam, setSectionsParam] = useState<string | null>(() =>
    searchParams.get("sections"),
  );
  const [editing, setEditing] = useState(false);
  // Whether edit mode opened on a blank grid ("New blank layout") rather than on
  // the current arrangement. Composing from nothing and saving under a name is
  // how a person builds a preset that shares no cards with what they see today.
  const [startBlank, setStartBlank] = useState(false);
  // Ephemeral collapse of a section on the page — the divider's saved `collapsed`
  // is the initial, and a click here folds or unfolds it for this visit only.
  const [collapseOverrides, setCollapseOverrides] = useState<Record<string, boolean>>({});
  // Overrides key on positional section ids (`custom-1`, …), so saving an edit or
  // applying a preset renumbers the sections and a leftover override would fold a
  // different one. A new `storedEntries` identity is exactly that renumbering, so
  // reset the map with it — during render, the pattern React recommends over an
  // effect for state that follows a changing value.
  const [overridesFor, setOverridesFor] = useState(storedEntries);
  if (overridesFor !== storedEntries) {
    setOverridesFor(storedEntries);
    setCollapseOverrides({});
  }
  const activeOrgId = useOrgStore((state) => state.activeOrgId);
  const organizations = useOrganizationList();
  const activeOrgName = useMemo(
    () => organizations.data?.find((organization) => organization.id === activeOrgId)?.name ?? null,
    [organizations.data, activeOrgId],
  );

  // can() answers false while permissions load; resolving the audience from
  // that would flash a viewer-shaped page at a steward, so hold the skeleton
  // until it is real. The saved arrangement is not held for: the hook reports
  // no preference while it loads, so the audience default renders first and a
  // saved arrangement settles it into place - the gate runs on both, so the
  // brief default is never a wider page than the person may see.
  if (isLoading) {
    return (
      <div className="space-y-6">
        <PageHeader title={t("title")} />
        <LoadingState variant="stats" />
      </div>
    );
  }

  const audience = resolveAudience(role, isAppAdmin);
  const isCustom = storedEntries !== null;
  const effective = resolveEffectiveLayout(audience, storedEntries);
  const visible = visibleSections(effective, can, isAppAdmin);

  const changePeriod = (next: Period) => {
    setPeriod(next);
    setUrlParam("period", formatPeriodParam(next));
  };
  const changeSections = (selected: string[] | null) => {
    const value = formatSectionsParam(selected);
    setSectionsParam(value);
    setUrlParam("sections", value);
  };

  const handleSave = async (entries: StoredEntry[]): Promise<boolean> => {
    try {
      await save(entries);
      setEditing(false);
      return true;
    } catch {
      toast.error(t("edit.saveFailed"));
      return false;
    }
  };
  const handleReset = async () => {
    try {
      await reset();
      setEditing(false);
    } catch {
      toast.error(t("edit.resetFailed"));
    }
  };
  // Applying a preset is a save of its entries, so the gate still runs last on
  // whatever it named - a preset can no more reveal a forbidden widget than a
  // hand-arranged layout can. The entries are sanitized first for the same
  // reason a saved layout is on read: a preset kept from before a widget was
  // retired would otherwise 422 the whole apply against the strict write
  // validator, where sanitizing drops the unknown id and applies the rest.
  const handleApplyPreset = async (preset: DashboardPreset) => {
    try {
      await save(toStored(sanitizeEntries(preset.entries)));
    } catch {
      toast.error(t("presets.applyFailed"));
    }
  };
  const handleSaveAsPreset = async (name: string, entries: StoredEntry[]) => {
    await savePreset(name, entries);
  };
  const openEditor = (blank: boolean) => {
    setStartBlank(blank);
    setEditing(true);
  };

  const resolveSectionTitle = (section: SectionDef): string => sectionLabel(section, t);

  // The editor works on a flat item list. A custom arrangement carries its own
  // dividers, so it is fed the sanitized, gated items directly rather than the
  // section-grouped layout (which would drop the dividers on the way in); an
  // audience default is flattened into dividers-plus-cards so its curated
  // sections arrive as real, editable headings a person can rename and recolour.
  const initialItems = startBlank
    ? []
    : storedEntries !== null
      ? visibleItems(sanitizeEntries(storedEntries), can, isAppAdmin)
      : flattenDefaultToItems(visible, resolveSectionTitle);

  if (editing) {
    return (
      <div className="space-y-6">
        <PageHeader title={t("title")} description={t("edit.subtitle")} />
        <DashboardEditor
          initialEntries={initialItems}
          catalog={widgetCatalog(can, isAppAdmin)}
          period={period}
          onSave={handleSave}
          onCancel={() => setEditing(false)}
          onReset={handleReset}
          onSaveAsPreset={handleSaveAsPreset}
          startedBlank={startBlank}
        />
      </div>
    );
  }

  // The arrange controls, then the page's one primary action - the position
  // every other page in the product puts its primary in (`New agent` on
  // Agents, `New collection` on Knowledge bases).
  const headerActions = (
    <div className="flex items-center gap-2">
      <div data-tour="dashboard-customize" className="flex items-center gap-2">
        <DashboardPresetMenu
          presets={presets}
          isCustom={isCustom}
          onApply={handleApplyPreset}
          onUseDefault={handleReset}
          onNewBlank={() => openEditor(true)}
          onDelete={removePreset}
        />
        <Button variant="outline" size="sm" className="gap-1.5" onClick={() => openEditor(false)}>
          <LayoutGrid className="size-3.5" aria-hidden />
          {t("edit.customize")}
        </Button>
      </div>
      {can(Perm.agentsRun) ? (
        <Button asChild size="sm" className="gap-1.5">
          <Link href={ROUTES.CHAT}>
            <MessageSquarePlus className="size-3.5" aria-hidden />
            {t("actions.newChat")}
          </Link>
        </Button>
      ) : null}
    </div>
  );

  // Empty is not failed: a person who hid every card sees an offer to reset and
  // to keep arranging, never a blank page that reads as broken.
  if (visible.length === 0) {
    return (
      <div className="space-y-6">
        <PageHeader title={t("title")} description={t(`subtitles.${audience}`)} />
        <EmptyState
          icon={LayoutGrid}
          title={t("edit.emptyTitle")}
          description={t("edit.emptyDescription")}
          cta={{ label: t("edit.customize"), onClick: () => openEditor(false) }}
          secondaryCta={isCustom ? { label: t("edit.reset"), onClick: handleReset } : undefined}
        />
      </div>
    );
  }

  const selectedSections = parseSectionsParam(sectionsParam, visible);
  const sections = applySectionsFilter(visible, selectedSections);
  const firstOrgSectionId = sections.find((section) => section.id !== "deployment")?.id;

  return (
    <div>
      <PageHeader
        title={t("title")}
        description={t(`subtitles.${audience}`)}
        actions={headerActions}
      />
      <FilterRow
        period={period}
        onPeriodChange={changePeriod}
        sections={visible}
        selectedSections={selectedSections}
        onSectionsChange={changeSections}
      />
      {/* The bands own a rhythm of their own, four times the gap between two
          cards, which is what makes a band read as a band. The header and the
          control strip above keep the 24px every other page uses. */}
      <div className={cn(BAND_GAP, "mt-6")}>
        {sections.map((section) => {
          // A custom divider carries the person's own caption (`title`) and an
          // accent; the curated defaults carry a translated `titleKey` and no
          // colour. Neutral is the absence of an accent — rendered plain, like a
          // default section — so only a real colour (a preset or a custom hex)
          // tints the band, carried on `--dash-solid` by the decoration.
          const heading = sectionLabel(section, t) || null;
          const coloured = isAccentColour(section.accent);
          const decoration = coloured ? accentDecoration(section.accent as string) : null;
          const collapsed =
            section.id in collapseOverrides ? collapseOverrides[section.id] : !!section.collapsed;
          const toggleCollapsed = () =>
            setCollapseOverrides((current) => ({ ...current, [section.id]: !collapsed }));
          return (
            <Fragment key={section.id}>
              {!isCustom && audience === "app_admin" && section.id === firstOrgSectionId ? (
                <OrgDivider name={activeOrgName} />
              ) : null}
              <section
                className={cn(coloured && "dash-section-accent p-4", decoration?.className)}
                style={decoration?.style as CSSProperties | undefined}
              >
                {/* A band label, not a title. A section heading set at the same
                  size and weight as the card titles under it gave the page two
                  levels where it has three, so nothing marked where one band
                  ended and the next began - the mono kicker `OrgDivider`
                  already used is the level between. */}
                {heading ? (
                  <h2 className="flex items-center gap-2">
                    <button
                      type="button"
                      onClick={toggleCollapsed}
                      aria-expanded={!collapsed}
                      aria-label={
                        collapsed
                          ? t("edit.expand", { title: heading })
                          : t("edit.collapse", { title: heading })
                      }
                      className="text-muted-foreground/70 hover:text-foreground -ml-1 flex size-5 shrink-0 items-center justify-center"
                    >
                      {collapsed ? (
                        <ChevronRight className="size-4" aria-hidden />
                      ) : (
                        <ChevronDown className="size-4" aria-hidden />
                      )}
                    </button>
                    {coloured ? (
                      <span className="dash-swatch size-2.5 shrink-0 rounded-full" aria-hidden />
                    ) : null}
                    <span className="text-muted-foreground truncate font-mono text-[11px] font-medium tracking-[0.1em] uppercase">
                      {heading}
                    </span>
                    <span className="bg-border h-px min-w-6 flex-1" aria-hidden />
                  </h2>
                ) : null}
                {collapsed ? null : (
                  <div className={cn(ARRANGED_GRID_CLASS, heading && HEADING_GAP)}>
                    {section.entries.map((entry, index) => {
                      const Widget = WIDGET_COMPONENTS[entry.widget];
                      // Width and height, both from the placement. The shipped
                      // default carries a height on every card now - it is a page
                      // somebody arranged - so this is the same grid an arranged
                      // layout renders in and the editor previews. A placement
                      // predating heights falls back to the widget's own.
                      const cell = `${SPAN_CLASS[entry.span]} ${ROW_CLASS[entry.rows ?? WIDGETS[entry.widget].defaultRows]}`;
                      return (
                        <div
                          key={`${entry.widget}-${index}`}
                          className={cn(cell, coloured && "dash-tile-accent")}
                        >
                          <Widget
                            title={t(entry.titleKey ?? `widgets.${entry.widget}.title`)}
                            hint={t(`widgets.${entry.widget}.description`)}
                            // A card pinning its own window gets that one; every
                            // other card follows the page's filter. Resolved here
                            // rather than inside the widget, so a widget never has
                            // to know which of the two it was handed - and so the
                            // preset is resolved once against one "today".
                            period={
                              entry.options?.period ? resolvePreset(entry.options.period) : period
                            }
                            seeAll={WIDGETS[entry.widget].seeAll}
                            options={entry.options}
                          />
                        </div>
                      );
                    })}
                  </div>
                )}
              </section>
            </Fragment>
          );
        })}
      </div>
    </div>
  );
}
