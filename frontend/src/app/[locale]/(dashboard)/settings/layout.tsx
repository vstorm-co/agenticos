"use client";

import type { ReactNode } from "react";

import { PageHeader } from "@/components/dashboard/page-header";
import { PageTabs } from "@/components/dashboard/page-tabs";

import { SETTINGS_TABS } from "./settings-tabs";
import { useTranslations } from "next-intl";

export default function SettingsLayout({ children }: { children: ReactNode }) {
  const t = useTranslations("pages.settings");
  return (
    <div className="space-y-6 pb-8">
      <PageHeader title={t("settings")} description={t("manageYourAccountIntegrations")} />
      <PageTabs tabs={SETTINGS_TABS} />
      <div className="min-w-0">{children}</div>
    </div>
  );
}
