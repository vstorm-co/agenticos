"use client";

import type { ReactNode } from "react";

import { PageHeader } from "@/components/dashboard/page-header";
import { PageSideNav, PageTabs } from "@/components/dashboard/page-tabs";

import { SETTINGS_TABS } from "./settings-tabs";
import { useTranslations } from "next-intl";

export default function SettingsLayout({ children }: { children: ReactNode }) {
  const t = useTranslations("pages.settings");
  return (
    <div className="space-y-6">
      <PageHeader title={t("settings")} description={t("manageYourAccountIntegrations")} />
      {/* Eight tabs did not fit across a readable column, so on a wide screen
          they stand beside it as a list - and the column stays narrow enough
          that a name field is not 1100px long for twenty characters. */}
      <div className="lg:grid lg:grid-cols-[12rem_minmax(0,1fr)] lg:items-start lg:gap-10">
        <div data-tour="settings-tabs" className="max-lg:mb-6 lg:sticky lg:top-6">
          <PageTabs tabs={SETTINGS_TABS} className="lg:hidden" />
          <PageSideNav tabs={SETTINGS_TABS} className="max-lg:hidden" />
        </div>
        <div className="max-w-4xl min-w-0">{children}</div>
      </div>
    </div>
  );
}
