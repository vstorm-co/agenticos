"use client";

import { use } from "react";
import { ShieldCheck } from "lucide-react";

import { PageHeader } from "@/components/dashboard/page-header";
import { EmptyState, LoadingState } from "@/components/states";
import { Badge, Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui";
import { usePermissions, useRoleCatalog } from "@/hooks";
import { ROUTES } from "@/lib/constants";
import type { PermissionScope } from "@/types/permissions";

interface PageProps {
  params: Promise<{ id: string }>;
}

/**
 * How a scope reads in the matrix. A resource permission is never a plain yes:
 * "which agents" is the whole point of the scope, so the cell shows it.
 */
const SCOPE_LABEL: Record<PermissionScope, string> = {
  none: "—",
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
  const { id: orgId } = use(params);
  const { catalog, isLoading } = useRoleCatalog();
  const { role: myRole, isAppAdmin } = usePermissions();

  // Nothing here waits on the catalog, so it renders while the matrix loads.
  const breadcrumbHeader = (
    <PageHeader
      title="Users & Roles"
      description="What each role may do. Permissions are defined in code and bundled into roles — a role can never hold a permission the platform does not define."
      breadcrumbs={[
        { label: "Organizations", href: ROUTES.ORGS },
        { label: "Members", href: ROUTES.ORG_MEMBERS(orgId) },
        { label: "Roles" },
      ]}
    />
  );

  if (isLoading) {
    return (
      <div className="space-y-6">
        {breadcrumbHeader}
        <Card>
          <CardHeader>
            <CardTitle>Permission matrix</CardTitle>
          </CardHeader>
          <CardContent>
            {/* The permission name plus one column per role — six roles ship in
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
      <EmptyState
        icon={ShieldCheck}
        title="Permission catalog unavailable"
        description="The server did not return the role catalog. Try reloading the page."
      />
    );
  }

  const resourcePerms = new Set(catalog.resource_permissions);
  const scopeFor = (roleName: string, permission: string): PermissionScope =>
    (catalog.roles
      .find((role) => role.name === roleName)
      ?.permissions.find((entry) => entry.permission === permission)?.scope as PermissionScope) ??
    "none";

  return (
    <div className="space-y-6">
      {breadcrumbHeader}

      <Card>
        <CardHeader>
          <CardTitle>Permission matrix</CardTitle>
          <CardDescription>
            Resource permissions carry a scope — <strong>own</strong> is what you created,{" "}
            <strong>shared</strong> adds what was shared with you, <strong>all</strong> is the whole
            organization. Sharing a single resource can widen access beyond the role, never narrow
            it.
            {myRole ? (
              <>
                {" "}
                Your role here is <Badge variant="secondary">{myRole}</Badge>
                {isAppAdmin ? " (platform superadmin — everything is permitted)" : null}.
              </>
            ) : null}
          </CardDescription>
        </CardHeader>
        <CardContent>
          {/* Wide table: scrolls inside its own container so the page never scrolls sideways. */}
          <div className="overflow-x-auto">
            <table className="w-full min-w-[46rem] text-sm">
              <thead>
                <tr className="border-b">
                  <th className="py-2 pr-4 text-left font-medium">Permission</th>
                  {catalog.roles.map((role) => (
                    <th key={role.name} className="px-3 py-2 text-left font-medium capitalize">
                      {role.name}
                    </th>
                  ))}
                </tr>
              </thead>
              <tbody>
                {catalog.all_permissions.map((permission) => (
                  <tr key={permission} className="border-b last:border-0">
                    <td className="py-2 pr-4 font-mono text-xs">
                      {permission}
                      {resourcePerms.has(permission) ? (
                        <span className="text-muted-foreground"> (scoped)</span>
                      ) : null}
                    </td>
                    {catalog.roles.map((role) => {
                      const scope = scopeFor(role.name, permission);
                      const isResource = resourcePerms.has(permission);
                      return (
                        <td key={role.name} className="px-3 py-2">
                          {scope === "none" ? (
                            <span className="text-muted-foreground">—</span>
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
              </tbody>
            </table>
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
