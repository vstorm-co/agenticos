"use client";

import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

import { PageHeader } from "@/components/dashboard/page-header";
import { PageTabs } from "@/components/dashboard/page-tabs";

import { SETTINGS_TABS } from "./settings-tabs";
import { useTranslations } from "next-intl";

export default function SettingsLayout({ children }: { children: ReactNode }) {
  const t = useTranslations("pages.settings");
  const memory = useTranslations("pages.memory");
  const isMemory = usePathname().endsWith("/settings/memory");
  return (
    <div className="flex flex-1 flex-col space-y-4">
      <PageHeader
        title={isMemory ? memory("title") : t("settings")}
        description={isMemory ? memory("description") : t("manageYourAccountIntegrations")}
      />
      <div data-tour="settings-tabs">
        <PageTabs tabs={SETTINGS_TABS} overflow="scroll" />
      </div>
      <div className="flex min-w-0 flex-1 flex-col">{children}</div>
    </div>
  );
}
