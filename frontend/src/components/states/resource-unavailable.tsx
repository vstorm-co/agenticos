"use client";

import { LockKeyhole } from "lucide-react";
import { useTranslations } from "next-intl";
import { useOrganizationList } from "@/hooks/use-organizations";
import { EmptyState } from "./empty-state";

/** A deliberately ambiguous missing/private resource, with a way back and a tenant hint. */
export function ResourceUnavailable({
  back,
  label,
  retry,
}: {
  back: string;
  label: string;
  retry?: { label: string; onClick: () => void };
}) {
  const t = useTranslations("ui.resourceUnavailable");
  const { data: organizations = [] } = useOrganizationList();
  return (
    <div className="border-border bg-card flex min-h-0 w-full flex-1 flex-col items-center justify-center rounded-xl border px-5 py-8">
      <EmptyState
        className="border-0 bg-transparent p-0 sm:p-0"
        icon={LockKeyhole}
        title={t("title")}
        description={t("description")}
        cta={{ label, href: back }}
        secondaryCta={retry}
      />
      {organizations.length > 1 && (
        <p className="text-muted-foreground mt-5 max-w-md text-center text-sm leading-relaxed">
          {t("switchOrganization")}
        </p>
      )}
    </div>
  );
}

/** A deep link keeps its destination visible while explaining the permission it needs. */
export function RunsPermissionNotice() {
  const t = useTranslations("ui.resourceUnavailable");
  return <EmptyState icon={LockKeyhole} title={t("runsTitle")} description={t("runsPermission")} />;
}
