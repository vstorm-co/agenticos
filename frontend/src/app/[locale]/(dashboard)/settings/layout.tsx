"use client";

import { usePathname } from "next/navigation";
import { useEffect, useRef, type ReactNode } from "react";

import { PageHeader } from "@/components/dashboard/page-header";
import { PageTabs } from "@/components/dashboard/page-tabs";

import { SETTINGS_TABS } from "./settings-tabs";
import { useTranslations } from "next-intl";

export default function SettingsLayout({ children }: { children: ReactNode }) {
  const t = useTranslations("pages.settings");
  const memory = useTranslations("pages.memory");
  const pathname = usePathname();
  const isMemory = pathname.endsWith("/settings/memory");
  const start = useRef<HTMLDivElement>(null);
  useEffect(() => {
    start.current?.scrollIntoView({ block: "start" });
  }, [pathname]);
  return (
    <div ref={start} className="flex flex-1 scroll-mt-16 flex-col space-y-4 lg:scroll-mt-6">
      <PageHeader
        title={isMemory ? memory("title") : t("settings")}
        description={isMemory ? memory("description") : t("manageYourAccountIntegrations")}
      />
      <div data-tour="settings-tabs">
        <PageTabs tabs={SETTINGS_TABS} overflow="scroll" />
      </div>
      <div className="flex min-h-0 w-full max-w-6xl min-w-0 flex-1 flex-col pb-6">{children}</div>
    </div>
  );
}
