"use client";

import type { ReactNode } from "react";

import { PageHeader } from "@/components/dashboard/page-header";
import { PageTabs } from "@/components/dashboard/page-tabs";

import { SETTINGS_TABS } from "./settings-tabs";

export default function SettingsLayout({ children }: { children: ReactNode }) {
  return (
    <div className="space-y-6 pb-8">
      <PageHeader
        title="Settings"
        description="Manage your account, integrations, notifications, and slash commands."
      />
      <PageTabs tabs={SETTINGS_TABS} />
      <div className="min-w-0">{children}</div>
    </div>
  );
}
