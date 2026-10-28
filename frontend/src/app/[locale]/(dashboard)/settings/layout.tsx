"use client";

import type { ReactNode } from "react";

import { PageHeader } from "@/components/dashboard/page-header";
import { PageTabs } from "@/components/dashboard/page-tabs";

import { SETTINGS_TABS } from "./settings-tabs";
import { useTranslations } from "next-intl";

export default function SettingsLayout({ children }: { children: ReactNode }) {
  const t = useTranslations("pages.settings");
  return (
    <div className="flex flex-1 flex-col space-y-6">
      <PageHeader title={t("settings")} description={t("manageYourAccountIntegrations")} />
      <div data-tour="settings-tabs">
        <PageTabs tabs={SETTINGS_TABS} />
      </div>
      <div className="flex min-w-0 flex-1 flex-col">{children}</div>
    </div>
  );
}
