"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui";
import { NativeDisclosure } from "@/components/ui/native-disclosure";
import type { SkillSection } from "@/types/providers";
import { SkillGrid } from "./skill-grid";
import { SkillSectionPages, type SectionFilters } from "./skill-section-pages";
import { SkillSectionTitle } from "./skill-section-title";

/**
 * The library arranged into sections, each folding open to its cards.
 *
 * A section carries its first cards; "show all" pages through the rest under
 * the same filters. Sections only order what the reader may already see - a
 * skill several agents serve appears under each of them.
 */
export function SkillSections({
  sections,
  filters,
  onOpen,
}: {
  sections: SkillSection[];
  filters: SectionFilters;
  onOpen: (id: string) => void;
}) {
  return (
    <div className="space-y-3">
      {sections.map((section) => (
        <SectionBlock key={section.key} section={section} filters={filters} onOpen={onOpen} />
      ))}
    </div>
  );
}

function SectionBlock({
  section,
  filters,
  onOpen,
}: {
  section: SkillSection;
  filters: SectionFilters;
  onOpen: (id: string) => void;
}) {
  const t = useTranslations("pages.skills");
  const [open, setOpen] = useState(true);
  const [all, setAll] = useState(false);
  const more = section.count > section.items.length;

  return (
    <NativeDisclosure
      open={open}
      onToggle={(event) => setOpen(event.currentTarget.open)}
      className="border-border rounded-xl border px-3 pb-1"
    >
      <summary className="px-1">
        <SkillSectionTitle section={section} />
      </summary>
      <div className="space-y-3 pt-2 pb-2">
        {all ? (
          <SkillSectionPages
            // A narrower search can leave fewer pages than the one being read.
            key={JSON.stringify(filters)}
            sectionKey={section.key}
            filters={filters}
            onOpen={onOpen}
          />
        ) : (
          <SkillGrid skills={section.items} onOpen={onOpen} />
        )}
        {more && (
          <Button variant="ghost" size="sm" onClick={() => setAll(!all)}>
            {all ? t("showFewer") : t("showAll", { count: section.count })}
          </Button>
        )}
      </div>
    </NativeDisclosure>
  );
}
