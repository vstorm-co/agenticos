"use client";

import { useTranslations } from "next-intl";

import { ShortcutSettings } from "@/components/desktop/shortcut-settings";
import { SectionHeading } from "@/components/ui";

/** A desktop app tab: shown in the tab row only inside the app (`settings-tabs.ts`). */
export default function ShortcutsPage() {
  const t = useTranslations("desktop.settings.shortcuts");

  return (
    <div className="space-y-6">
      <SectionHeading title={t("heading")} description={t("headingHint")} />
      <ShortcutSettings />
    </div>
  );
}
