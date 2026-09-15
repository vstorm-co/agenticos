"use client";

import { MyMemory } from "@/components/memory/my-memory";
import { PageHeader } from "@/components/dashboard/page-header";
import { useTranslations } from "next-intl";

/**
 * Your own memory: what agents here have written down about you.
 *
 * Under `/settings/` because it is yours rather than the organization's, and no
 * permission gates it - the answer is the same for a Viewer and an Owner (#1594).
 */
export default function MemoryPage() {
  const t = useTranslations("pages.memory");

  return (
    <div className="space-y-6">
      <PageHeader title={t("title")} description={t("description")} />
      <MyMemory />
    </div>
  );
}
