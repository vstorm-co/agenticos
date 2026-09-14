"use client";

import Link from "next/link";
import { useParams } from "next/navigation";
import { ChevronLeft } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import { EmptyState, ErrorState, LoadingState } from "@/components/states";
import { Badge } from "@/components/ui";
import { useAdminOrganizationDetail } from "@/hooks";
import { getErrorMessage } from "@/lib/api-error";
import { ROUTES } from "@/lib/constants";
import { formatDate } from "@/lib/utils";

/**
 * One tenant the deployment admin can open without joining it (#1245).
 *
 * The destination the admin user-drawer's organization row links to. Metadata
 * only - members and their roles, size, owner and budget - because the tenant
 * boundary keeps a tenant's agents, conversations and secrets to the tenant; the
 * backend read is app-admin-only and audited. Deep under `/admin`, so it carries
 * no onboarding stop by the same rule the rest of the section does.
 */
export default function AdminOrganizationDetailPage() {
  const t = useTranslations("pages.admin");
  const tErrors = useTranslations("errors");
  const locale = useLocale();
  const params = useParams<{ id: string }>();
  const { organization, isLoading, error } = useAdminOrganizationDetail(params.id);

  return (
    <div className="mx-auto max-w-3xl space-y-6">
      <Link
        href={ROUTES.ADMIN_ORGANIZATIONS}
        className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1 text-sm"
      >
        <ChevronLeft className="h-4 w-4" aria-hidden />
        {t("backToOrganizations")}
      </Link>

      {isLoading ? (
        <LoadingState variant="skeleton-list" rows={3} />
      ) : error ? (
        <ErrorState
          title={t("orgDetailCouldNotBeRead")}
          description={getErrorMessage(error, tErrors, t("orgDetailCouldNotBeRead"))}
        />
      ) : !organization ? (
        <EmptyState title={t("orgNotFound")} description={t("orgNotFoundHint")} />
      ) : (
        <>
          <header className="flex flex-wrap items-center gap-3">
            <h1 className="text-foreground text-xl font-semibold">{organization.name}</h1>
            {organization.is_personal && <Badge variant="outline">{t("personal")}</Badge>}
            <span className="text-muted-foreground font-mono text-xs">{organization.slug}</span>
          </header>

          <dl className="grid grid-cols-2 gap-4 sm:grid-cols-3">
            <div>
              <dt className="text-muted-foreground text-xs">{t("owner")}</dt>
              <dd className="text-foreground text-sm">
                {organization.owner_email ?? t("noOwner")}
              </dd>
            </div>
            <div>
              <dt className="text-muted-foreground text-xs">{t("monthlyBudgetUsd")}</dt>
              <dd className="text-foreground text-sm tabular-nums">
                {organization.monthly_budget_usd ?? t("noBudget")}
              </dd>
            </div>
            <div>
              <dt className="text-muted-foreground text-xs">{t("members")}</dt>
              <dd className="text-foreground text-sm tabular-nums">{organization.member_count}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground text-xs">{t("agents")}</dt>
              <dd className="text-foreground text-sm tabular-nums">{organization.agent_count}</dd>
            </div>
            <div>
              <dt className="text-muted-foreground text-xs">{t("created")}</dt>
              <dd className="text-foreground text-sm">
                {formatDate(organization.created_at, locale)}
              </dd>
            </div>
          </dl>

          <section className="space-y-2">
            <h2 className="text-foreground text-sm font-semibold">{t("members")}</h2>
            {organization.members.length === 0 ? (
              <p className="text-muted-foreground text-xs">{t("noMembers")}</p>
            ) : (
              <ul className="space-y-1">
                {organization.members.map((member) => (
                  <li
                    key={member.user_id}
                    className="border-border bg-background flex items-center justify-between gap-2 rounded-lg border px-3 py-2"
                  >
                    <span className="text-foreground min-w-0 flex-1 truncate text-xs">
                      {member.name ?? member.email}
                    </span>
                    <span className="text-muted-foreground shrink-0 text-xs">{member.role}</span>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </>
      )}
    </div>
  );
}
