"use client";

import { useTranslations } from "next-intl";
import { LoadingState } from "@/components/states";
import { Button, Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui";
import { useRoleNavigation } from "@/hooks/use-role-navigation";
import { getErrorMessage } from "@/lib/api-error";
import { useOrgStore } from "@/stores";
import type { RoleCatalog } from "@/types/permissions";
import { RoleNavigationForm } from "./role-navigation-form";

export function RoleNavigationEditor({
  organizationId,
  catalog,
}: {
  organizationId: string;
  catalog: RoleCatalog;
}) {
  const t = useTranslations("pages.orgs.navigation");
  const errors = useTranslations("errors");
  const activeOrgId = useOrgStore((state) => state.activeOrgId);
  const query = useRoleNavigation(organizationId);

  return (
    <Card>
      <CardHeader className="border-b px-5 py-4" data-tour="org-role-navigation">
        <CardTitle className="text-sm">{t("title")}</CardTitle>
        <CardDescription>{t("description")}</CardDescription>
      </CardHeader>
      <CardContent className="space-y-5 p-5">
        <p className="text-muted-foreground text-sm">{t("accessNotice")}</p>
        {query.isPending || activeOrgId !== organizationId ? (
          <LoadingState variant="pending" />
        ) : (
          <>
            {query.isError ? (
              <div className="space-y-3" role="alert">
                <p>{t("loadError")}</p>
                <p className="text-muted-foreground text-sm">
                  {getErrorMessage(query.error, errors)}
                </p>
                <Button variant="outline" onClick={() => void query.refetch()}>
                  {t("retry")}
                </Button>
              </div>
            ) : null}
            {query.data ? (
              <RoleNavigationForm
                key={organizationId}
                organizationId={organizationId}
                catalog={catalog}
                policy={query.data}
              />
            ) : null}
          </>
        )}
      </CardContent>
    </Card>
  );
}
