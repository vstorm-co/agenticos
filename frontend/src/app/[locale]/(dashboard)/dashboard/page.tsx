import { Construction } from "lucide-react";

import { PageHeader } from "@/components/dashboard/page-header";
import { EmptyState } from "@/components/states";
import { ROUTES } from "@/lib/constants";
import { useTranslations } from "next-intl";

export default function DashboardPage() {
  const t = useTranslations("pages.dashboard");
  return (
    <div className="pb-8">
      <PageHeader title={t("dashboard")} description={t("pageBeingRebuiltWidgets")} />
      <EmptyState
        icon={Construction}
        title={t("underConstruction")}
        description={t("weReReworkingWhat")}
        cta={{ label: t("goChat"), href: ROUTES.CHAT }}
        secondaryCta={{ label: t("agents2"), href: ROUTES.AGENTS }}
      />
    </div>
  );
}
