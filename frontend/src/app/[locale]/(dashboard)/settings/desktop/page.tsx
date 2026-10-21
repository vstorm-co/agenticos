"use client";

import { useTranslations } from "next-intl";

import { WindowSettings } from "@/components/desktop/window-settings";
import { SectionHeading } from "@/components/ui";

/** A desktop app tab: shown in the tab row only inside the app (`settings-tabs.ts`). */
export default function DesktopAppPage() {
  const t = useTranslations("desktop.settings.window");

  return (
    <div className="space-y-6">
      <SectionHeading title={t("heading")} description={t("headingHint")} />
      <WindowSettings />
    </div>
  );
}
