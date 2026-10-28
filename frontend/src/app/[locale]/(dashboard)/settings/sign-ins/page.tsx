"use client";

import { useTranslations } from "next-intl";

import { MySignIns } from "@/components/browser/my-sign-ins";
import { SectionHeading } from "@/components/ui";

/**
 * Your kept browser sign-ins (#2129).
 *
 * Under `/settings/` because they are yours rather than the organization's: a
 * sign-in is kept for the person who made it and used only by browses acting as
 * them, so no permission gates the page.
 */
export default function SignInsPage() {
  const t = useTranslations("pages.signIns");

  return (
    <div className="flex flex-1 flex-col space-y-6">
      <SectionHeading title={t("title")} description={t("description")} />
      <MySignIns />
    </div>
  );
}
