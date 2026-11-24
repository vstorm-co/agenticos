"use client";

import { useTranslations } from "next-intl";

import { PageHeader } from "@/components/dashboard/page-header";
import { NetworkConnections } from "@/components/connections/network-connections";

export default function DevicesAndNetworksPage() {
  const t = useTranslations("networkConnections");
  return (
    <div className="flex flex-1 flex-col space-y-4">
      <PageHeader title={t("pageTitle")} description={t("pageDescription")} />
      <NetworkConnections />
    </div>
  );
}
