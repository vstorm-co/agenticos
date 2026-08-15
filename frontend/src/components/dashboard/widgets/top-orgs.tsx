"use client";

import { useTranslations } from "next-intl";

import { useAdminOrganizations } from "@/hooks";
import { MemberIdentity } from "@/components/orgs/member-identity";
import { WidgetFrame } from "../widget-frame";
import { WidgetEmptyBody, WidgetErrorBody, WidgetSkeleton } from "../widget-states";
import type { DashboardWidgetProps } from "./types";

/** The largest organizations, by people and agents. */
export function TopOrgsWidget({ title, hint, seeAll, options }: DashboardWidgetProps) {
  const t = useTranslations("dashboard.widgets.top-orgs");
  const { organizations, isLoading, error, refetch } = useAdminOrganizations(5);

  return (
    <WidgetFrame title={title} hint={hint} seeAll={seeAll} options={options}>
      {isLoading ? (
        <WidgetSkeleton />
      ) : error ? (
        <WidgetErrorBody onRetry={() => refetch()} />
      ) : organizations.length === 0 ? (
        <WidgetEmptyBody title={t("empty.title")} description={t("empty.description")} />
      ) : (
        <table className="w-full text-sm">
          <thead>
            <tr className="text-muted-foreground text-left text-xs">
              <th className="pb-2 font-normal">{t("organization")}</th>
              <th className="pb-2 font-normal">{t("owner")}</th>
              <th className="pb-2 text-right font-normal">{t("members")}</th>
              <th className="pb-2 text-right font-normal">{t("agents")}</th>
            </tr>
          </thead>
          <tbody>
            {organizations.map((organization) => (
              <tr key={organization.id} className="border-border border-t">
                <td className="text-foreground max-w-0 truncate py-1.5 pr-2">
                  {organization.name}
                </td>
                {/* Who to ask about this tenant. A list of counts says how big
                    an organization is and nothing about who answers for it,
                    which is the first thing a deployment admin needs. An
                    organization with no owner left says so rather than showing
                    an empty cell that reads as a rendering bug. */}
                <td className="max-w-0 py-1.5 pr-2">
                  {organization.owner_user_id && organization.owner_email ? (
                    <MemberIdentity
                      member={{
                        user_id: organization.owner_user_id,
                        email: organization.owner_email,
                        full_name: organization.owner_name,
                      }}
                    />
                  ) : (
                    <span className="text-muted-foreground text-xs">{t("noOwner")}</span>
                  )}
                </td>
                <td className="py-1.5 text-right tabular-nums">{organization.member_count}</td>
                <td className="py-1.5 text-right tabular-nums">{organization.agent_count}</td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </WidgetFrame>
  );
}
