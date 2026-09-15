"use client";

import { use, useEffect, useState } from "react";
import { Archive } from "lucide-react";

import { PageHeader } from "@/components/dashboard/page-header";
import { RetentionForm } from "@/components/orgs/retention-form";
import { EmptyState, LoadingState } from "@/components/states";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui";
import { usePermissions, useRetention } from "@/hooks";
import { ROUTES } from "@/lib/constants";
import { Perm } from "@/types/permissions";
import { useTranslations } from "next-intl";

interface PageProps {
  params: Promise<{ id: string }>;
}

/**
 * How long this organization keeps each class of data.
 *
 * Gated on `org:settings` the way the rest of the organization's settings are,
 * and gated for reading as much as for writing: how long a tenant keeps what its
 * people said is a statement about the tenant, not a fact every member needs. The
 * server refuses either way; this only decides whether the page is drawn (#1420).
 */
export default function RetentionPage({ params }: PageProps) {
  const t = useTranslations("pages.retention");
  const { id: orgId } = use(params);
  const { can } = usePermissions();
  const { policy, isLoading, isSaving, save } = useRetention(orgId);
  const [saved, setSaved] = useState(false);

  // The confirmation is a moment, not a state: it clears itself so a person who
  // comes back to the tab an hour later is not told about a save they have
  // forgotten making.
  useEffect(() => {
    if (!saved) return;
    const timer = setTimeout(() => setSaved(false), 4000);
    return () => clearTimeout(timer);
  }, [saved]);

  const header = (
    <PageHeader
      title={t("title")}
      description={t("description")}
      breadcrumbs={[
        { label: t("organizations"), href: ROUTES.ORGS },
        { label: t("members"), href: ROUTES.ORG_MEMBERS(orgId) },
        { label: t("title") },
      ]}
    />
  );

  if (!can(Perm.orgSettings)) {
    return (
      <div className="space-y-6">
        {header}
        <EmptyState icon={Archive} title={t("notYours")} description={t("askAnAdmin")} />
      </div>
    );
  }

  return (
    <div className="space-y-6">
      {header}
      <Card data-tour="org-retention">
        <CardHeader className="border-b px-5 py-4">
          <CardTitle className="text-sm">{t("howLongEachClassLives")}</CardTitle>
        </CardHeader>
        <CardContent className="p-5">
          {isLoading || !policy ? (
            <LoadingState variant="skeleton-table" columns={3} rows={6} />
          ) : (
            <RetentionForm
              policy={policy}
              isSaving={isSaving}
              saved={saved}
              onSave={async (days) => {
                await save(days);
                setSaved(true);
              }}
            />
          )}
        </CardContent>
      </Card>
    </div>
  );
}
