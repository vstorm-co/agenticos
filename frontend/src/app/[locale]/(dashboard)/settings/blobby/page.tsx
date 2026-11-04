"use client";

import { useTranslations } from "next-intl";

import { BlobbySettingsPanel } from "@/components/desktop/blobby-settings";
import { SectionHeading } from "@/components/ui";

/** A desktop app tab: shown in the tab row only inside the app (`settings-tabs.ts`). */
export default function BlobbyPage() {
  const t = useTranslations("desktop.settings.blobby");

  return (
    <div className="space-y-6">
      <SectionHeading title={t("heading")} description={t("headingHint")} />
      <BlobbySettingsPanel />
    </div>
  );
}
