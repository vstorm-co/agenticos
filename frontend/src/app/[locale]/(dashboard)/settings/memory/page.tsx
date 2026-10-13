"use client";

import { MyMemory } from "@/components/memory/my-memory";
import { SectionHeading } from "@/components/ui";
import { useTranslations } from "next-intl";

/**
 * Your own memory: what agents here have written down about you.
 *
 * Under `/settings/` because it is yours rather than the organization's, and no
 * permission gates it - the answer is the same for a Viewer and an Owner (#1594).
 *
 * A section heading rather than a page header: the settings layout already
 * draws the page's title and its help button, and a second of each stacked
 * under the tabs read as a different page opened inside this one.
 */
export default function MemoryPage() {
  const t = useTranslations("pages.memory");

  return (
    <div className="space-y-6">
      <SectionHeading title={t("title")} description={t("description")} />
      <MyMemory />
    </div>
  );
}
