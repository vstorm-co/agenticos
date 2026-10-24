"use client";

import { LockKeyhole } from "lucide-react";
import { useTranslations } from "next-intl";
import { useOrganizationList } from "@/hooks/use-organizations";
import { EmptyState } from "./empty-state";

/** A deliberately ambiguous missing/private resource, with a way back and a tenant hint. */
export function ResourceUnavailable({ back, label }: { back: string; label: string }) {
  const t = useTranslations("ui.resourceUnavailable");
  const { data: organizations = [] } = useOrganizationList();
  return (
    <div className="space-y-3">
      <EmptyState
        icon={LockKeyhole}
        title={t("title")}
        description={t("description")}
        cta={{ label, href: back }}
      />
      {organizations.length > 1 && (
        <p className="text-muted-foreground text-center text-sm">{t("switchOrganization")}</p>
      )}
    </div>
  );
}

/** A deep link keeps its destination visible while explaining the permission it needs. */
export function RunsPermissionNotice() {
  const t = useTranslations("ui.resourceUnavailable");
  return <EmptyState icon={LockKeyhole} title={t("runsTitle")} description={t("runsPermission")} />;
}
