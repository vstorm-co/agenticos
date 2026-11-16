"use client";

import { use, useId, useState } from "react";
import { Search } from "lucide-react";

import { PageHeader } from "@/components/dashboard/page-header";
import { ErrorState, LoadingState } from "@/components/states";
import {
  Badge,
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
  SearchInput,
  Skeleton,
  ListCardEmpty,
} from "@/components/ui";
import { usePermissions, useRoleCatalog } from "@/hooks";
import { ROUTES } from "@/lib/constants";
import type { PermissionScope } from "@/types/permissions";
import { useTranslations } from "next-intl";

interface PageProps {
  params: Promise<{ id: string }>;
}

/**
 * How a scope reads in the matrix. A resource permission is never a plain yes:
 * "which agents" is the whole point of the scope, so the cell shows it.
 */
const SCOPE_LABEL: Record<PermissionScope, string> = {
  none: "-",
  own: "own",
  shared: "shared",
  team: "team",
  all: "all",
};

const SCOPE_VARIANT: Record<PermissionScope, "default" | "secondary" | "outline"> = {
  none: "outline",
  own: "outline",
  shared: "secondary",
  team: "secondary",
  all: "default",
};

export default function RolesPage({ params }: PageProps) {
  const t = useTranslations("pages.orgs");
  const matrixId = useId();
  const [query, setQuery] = useState("");
  const { id: orgId } = use(params);
  const { catalog, isLoading } = useRoleCatalog();
  const { role: myRole, isAppAdmin } = usePermissions();

  // Nothing here waits on the catalog, so it renders while the matrix loads.
  const breadcrumbHeader = (
    <PageHeader
      title={t("usersRoles")}
      description={t("whatEachRoleMay")}
      breadcrumbs={[
        { label: t("organizations2"), href: ROUTES.ORGS },
        { label: t("members3"), href: ROUTES.ORG_MEMBERS(orgId) },
        { label: t("roles") },
      ]}
    />
  );

  const toolbar = (
    <div className="border-b px-4 py-3 sm:px-5">
      <SearchInput
        value={query}
        onChange={setQuery}
        placeholder={t("searchPermissions")}
        className="w-full sm:max-w-sm"
      />
    </div>
  );

  if (isLoading) {
    return (
      <div className="flex min-h-0 flex-1 flex-col gap-4">
        {breadcrumbHeader}
        <Card className="flex min-h-0 flex-1 flex-col">
          <CardHeader className="border-b px-5 py-4">
            <CardTitle className="text-sm">{t("permissionMatrix")}</CardTitle>
            <CardDescription>
              <Skeleton className="h-4 w-full" />
            </CardDescription>
          </CardHeader>
          {toolbar}
          <CardContent className="flex-1 p-0">
            {/* The permission name plus one column per role - six roles ship in
                the catalog. A wrong guess costs a column of width, not the
                page's height, which is what the reader is waiting on. */}
            <LoadingState variant="skeleton-table" columns={7} rows={12} />
          </CardContent>
        </Card>
      </div>
    );
  }

  if (!catalog) {
    return (
      <div className="flex flex-1 flex-col gap-4">
        {breadcrumbHeader}
        <ErrorState
          title={t("permissionCatalogUnavailable")}
          description={t("serverDidNotReturn")}
        />
      </div>
    );
  }

  const resourcePerms = new Set(catalog.resource_permissions);
  const scopeFor = (roleName: string, permission: string): PermissionScope =>
    catalog.roles
      .find((role) => role.name === roleName)
      ?.permissions.find((entry) => entry.permission === permission)?.scope ?? "none";

  const shown = catalog.all_permissions.filter((permission) =>
    permission.toLowerCase().includes(query.trim().toLowerCase()),
  );

  return (
    <div className="flex min-h-0 flex-1 flex-col gap-4">
      {breadcrumbHeader}

      <Card data-tour="org-roles" className="flex min-h-0 flex-1 flex-col">
        <CardHeader className="border-b px-5 py-4">
          <CardTitle id={matrixId} className="text-sm">
            {t("permissionMatrix2")}
          </CardTitle>
          <CardDescription className="text-xs">
            {t.rich("scopeDescription", {
              strong: (chunks) => <strong>{chunks}</strong>,
            })}
            {myRole ? (
              <>
                {" "}
                {t.rich("yourRoleHere", {
                  role: myRole,
                  badge: (chunks) => (
                    <Badge variant="secondary" className="capitalize">
                      {chunks}
                    </Badge>
                  ),
                })}
                {isAppAdmin ? t("platformSuperadmin") : null}.
              </>
            ) : null}
          </CardDescription>
        </CardHeader>
        {toolbar}
        <CardContent className="flex min-h-0 flex-1 flex-col p-0">
          {/* Wide table: scrolls inside its own container so the page never scrolls sideways. */}
          <div
            role="region"
            aria-labelledby={matrixId}
            // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex -- A scroll region needs focus for native arrow-key scrolling.
            tabIndex={0}
            className="focus-visible:outline-ring min-h-64 flex-1 overflow-auto overscroll-contain focus-visible:outline-2 focus-visible:-outline-offset-2"
          >
            <table className="w-full min-w-[46rem] border-separate border-spacing-0 text-sm">
              <thead className="bg-card sticky top-0 z-20">
                <tr className="border-b">
                  <th
                    scope="col"
                    className="bg-card text-muted-foreground sticky left-0 z-30 border-b px-5 py-3 text-left text-xs font-medium"
                  >
                    {t("permission")}
                  </th>
                  {catalog.roles.map((role) => (
                    <th
                      key={role.name}
                      scope="col"
                      className="bg-card text-muted-foreground border-b px-3 py-3 text-left text-xs font-medium capitalize"
                    >
                      {role.name}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {shown.map((permission) => (
                  <tr key={permission} className="border-b last:border-0">
                    <th
                      scope="row"
                      className="bg-card sticky left-0 z-10 border-b px-5 py-3 text-left font-mono text-xs font-normal shadow-[1px_0_0_var(--border)]"
                    >
                      {permission}
                      {resourcePerms.has(permission) ? (
                        <span className="text-muted-foreground"> {t("scoped")}</span>
                      ) : null}
                    </th>
                    {catalog.roles.map((role) => {
                      const scope = scopeFor(role.name, permission);
                      const isResource = resourcePerms.has(permission);
                      return (
                        <td key={role.name} className="border-b px-3 py-3">
                          {scope === "none" ? (
                            <span className="text-muted-foreground">-</span>
                          ) : (
                            <Badge variant={SCOPE_VARIANT[scope]}>
                              {isResource ? SCOPE_LABEL[scope] : "yes"}
                            </Badge>
                          )}
                        </td>
                      );
                    })}
                  </tr>
                ))}
                {shown.length === 0 && (
                  <tr>
                    <td colSpan={catalog.roles.length + 1}>
                      <ListCardEmpty
                        icon={Search}
                        title={t("noPermissionsMatch")}
                        onClearFilters={() => setQuery("")}
                      />
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
