"use client";

import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";

import { Badge, DataTable, ListCard, type Column } from "@/components/ui";
import { apiClient } from "@/lib/api-client";
import { qk } from "@/lib/query-keys";
import { formatDate } from "@/lib/utils";
import { useLocale, useTranslations } from "next-intl";

import type { AdminOrganization } from "@/types/admin";

/**
 * Every tenant on the deployment, one row each - its own tab rather than a
 * table at the bottom of the overview, where it competed with the figures for
 * a reader who came for exactly one of the two.
 *
 * No sort headers on purpose: the fetch is one server page, so a client sort
 * would claim a whole-collection order fifty rows cannot deliver - the same
 * reasoning that keeps them off the org members table.
 */
export default function AdminOrganizationsPage() {
  const t = useTranslations("pages.admin");
  const locale = useLocale();

  const { data: orgs, error } = useQuery({
    queryKey: qk.admin.organizations(),
    queryFn: async (): Promise<AdminOrganization[]> => {
      const data = await apiClient.get<{ items: AdminOrganization[] }>(
        "/admin/organizations?limit=50",
      );
      return data.items;
    },
  });

  const columns = useMemo<Column<AdminOrganization>[]>(
    () => [
      {
        key: "name",
        header: t("name"),
        className: "pl-5",
        cell: (org) => (
          <>
            <span className="text-foreground font-medium">{org.name}</span>
            {org.is_personal && (
              <Badge variant="outline" className="ml-2 text-[10px]">
                {t("personal")}
              </Badge>
            )}
          </>
        ),
      },
      {
        key: "slug",
        header: t("slug"),
        cell: (org) => <span className="text-muted-foreground font-mono text-xs">{org.slug}</span>,
      },
      {
        key: "members",
        header: t("members"),
        align: "right",
        cell: (org) => <span className="tabular-nums">{org.member_count}</span>,
      },
      {
        key: "agents",
        header: t("agents2"),
        align: "right",
        cell: (org) => <span className="tabular-nums">{org.agent_count}</span>,
      },
      {
        key: "created",
        header: t("created"),
        align: "right",
        className: "pr-5",
        cell: (org) => (
          <span className="text-muted-foreground text-xs">
            {formatDate(org.created_at, locale)}
          </span>
        ),
      },
    ],
    [t, locale],
  );

  return (
    <ListCard
      title={t("organizations2")}
      counted={t("everyTenantDeploymentOnly")}
      contentClassName="p-0"
    >
      <DataTable<AdminOrganization>
        columns={columns}
        rows={orgs}
        getRowKey={(org) => org.id}
        loading={orgs === undefined && error === null}
        skeletonRows={4}
        error={error !== null ? t("organizationsCouldNotBeRead") : null}
        empty={t("noOrganizationsYet")}
        className="rounded-none border-0 bg-transparent [&_table]:min-w-[36rem]"
      />
    </ListCard>
  );
}
