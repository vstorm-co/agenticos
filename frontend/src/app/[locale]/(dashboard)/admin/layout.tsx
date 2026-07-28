"use client";

import type { ReactNode } from "react";

import { PageHeader } from "@/components/dashboard/page-header";
import { PageTabs } from "@/components/dashboard/page-tabs";

import { ADMIN_TABS } from "./admin-tabs";

export default function AdminLayout({ children }: { children: ReactNode }) {
  return (
    <div className="space-y-6 pb-8">
      <PageHeader
        title="Workspace administration"
        description="Users, conversations, ratings, and system health."
      />
      <PageTabs tabs={ADMIN_TABS} />
      <div className="min-w-0">{children}</div>
    </div>
  );
}
