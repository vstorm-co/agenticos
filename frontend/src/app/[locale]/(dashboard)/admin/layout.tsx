"use client";

import type { ReactNode } from "react";

import { PageHeader } from "@/components/dashboard/page-header";
import { PageTabs } from "@/components/dashboard/page-tabs";

import { ADMIN_TABS } from "./admin-tabs";
import { useTranslations } from "next-intl";

export default function AdminLayout({ children }: { children: ReactNode }) {
  const t = useTranslations("pages.admin");
  return (
    <div className="flex flex-1 flex-col space-y-6">
      <PageHeader
        title={t("workspaceAdministration")}
        description={t("usersConversationsOrgsSystem")}
      />
      <PageTabs tabs={ADMIN_TABS} />
      <div className="flex min-w-0 flex-1 flex-col">{children}</div>
    </div>
  );
}
