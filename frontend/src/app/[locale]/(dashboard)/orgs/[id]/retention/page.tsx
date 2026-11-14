"use client";

import { use, useEffect, useState } from "react";
import { Archive } from "lucide-react";

import { PageHeader } from "@/components/dashboard/page-header";
import { RetentionFormLoading } from "@/components/orgs/retention-table";
import { RetentionForm } from "@/components/orgs/retention-form";
import { EmptyState, ErrorState } from "@/components/states";
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
  const tc = useTranslations("common");
  const { id: orgId } = use(params);
  const { can, isLoaded, error: permissionsError } = usePermissions();
  const { policy, isLoading, error, refetch, isSaving, save } = useRetention(orgId);
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

  // `can()` answers false while the permission set is loading and after it
  // fails, so deciding on it alone flashes "not an administrator" at every Owner
  // on navigation and leaves a failed read saying it permanently (#1420 review).
  if (permissionsError) {
    return (
      <div className="flex min-h-0 flex-1 flex-col gap-4">
        {header}
        <ErrorState />
      </div>
    );
  }
  if (!isLoaded) {
    return (
      <div className="flex min-h-0 flex-1 flex-col gap-4">
        {header}
        <Card className="flex min-h-0 flex-1 flex-col">
          <CardHeader className="border-b px-5 py-4">
            <CardTitle className="text-sm">{t("howLongEachClassLives")}</CardTitle>
          </CardHeader>
          <CardContent className="flex flex-1 flex-col p-0">
            <RetentionFormLoading />
          </CardContent>
        </Card>
      </div>
    );
  }
  if (!can(Perm.orgSettings)) {
    return (
      <div className="flex min-h-0 flex-1 flex-col gap-4">
        {header}
        <EmptyState icon={Archive} title={t("notYours")} description={t("askAnAdmin")} />
      </div>
    );
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4">
      {header}
      <Card data-tour="org-retention" className="flex min-h-0 flex-1 flex-col">
        <CardHeader className="border-b px-5 py-4">
          <CardTitle className="text-sm">{t("howLongEachClassLives")}</CardTitle>
        </CardHeader>
        <CardContent className="flex min-h-0 flex-1 flex-col p-0">
          {error ? (
            <ErrorState cta={{ label: tc("retry"), onClick: () => void refetch() }} />
          ) : isLoading || !policy ? (
            <RetentionFormLoading />
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
