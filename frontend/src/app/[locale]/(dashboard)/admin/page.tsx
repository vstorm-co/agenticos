"use client";

import Link from "next/link";
import { useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  ArrowUpRight,
  Bot,
  Building2,
  MessageSquare,
  MessagesSquare,
  Star,
  UserPlus,
  Users,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { StatCard } from "@/components/dashboard/stat-card";
import { LoadingState } from "@/components/states";
import { Badge, DataTable, ListCard, type Column } from "@/components/ui";
import { apiClient } from "@/lib/api-client";
import { ROUTES } from "@/lib/constants";
import { qk } from "@/lib/query-keys";
import { formatDate, timeAgo } from "@/lib/utils";
import { useLocale, useTranslations } from "next-intl";

import type { AdminOrganization, AdminStats } from "@/types/admin";

interface RecentEvent {
  id: string;
  type: "user_signup" | "conversation_created" | "rating_low";
  title: string;
  description: string;
  timestamp: string;
}

const EVENT_ICON: Record<RecentEvent["type"], LucideIcon> = {
  user_signup: UserPlus,
  conversation_created: MessageSquare,
  rating_low: Star,
};

export default function AdminOverviewPage() {
  const t = useTranslations("pages.admin");
  const tTime = useTranslations("time");
  const locale = useLocale();
  const statsQuery = useQuery({
    queryKey: qk.admin.stats(),
    queryFn: async (): Promise<AdminStats> => {
      const data = await apiClient.get<AdminStats>("/admin/stats").catch(() => null);
      if (data) return data;
      const [usersResp, convsResp] = await Promise.allSettled([
        apiClient.get<{ total: number }>("/admin/users?limit=1"),
        apiClient.get<{ total: number }>("/admin/conversations?limit=1"),
      ]);
      return {
        total_users: usersResp.status === "fulfilled" ? usersResp.value.total : undefined,
        total_conversations: convsResp.status === "fulfilled" ? convsResp.value.total : undefined,
      };
    },
  });

  const orgsQuery = useQuery({
    queryKey: qk.admin.organizations(),
    queryFn: async (): Promise<AdminOrganization[]> => {
      const data = await apiClient
        .get<{ items: AdminOrganization[] }>("/admin/organizations?limit=50")
        .catch(() => null);
      return data?.items ?? [];
    },
  });

  const eventsQuery = useQuery({
    queryKey: qk.admin.events(),
    queryFn: async (): Promise<RecentEvent[]> => {
      const events = await apiClient
        .get<{ items: RecentEvent[] }>("/admin/events")
        .catch(() => null);
      if (events) return events.items.slice(0, 8);
      const convs = await apiClient
        .get<{
          items: Array<{ id: string; user_email?: string; title?: string; created_at: string }>;
        }>("/admin/conversations?limit=8")
        .catch(() => ({ items: [] }));
      return convs.items.map((c) => ({
        id: c.id,
        type: "conversation_created" as const,
        title: c.title || t("newConversation"),
        description: c.user_email ? t("byUser", { email: c.user_email }) : "",
        timestamp: c.created_at,
      }));
    },
  });

  const stats = statsQuery.data;
  const events = eventsQuery.data;
  const orgs = orgsQuery.data;

  const orgColumns = useMemo<Column<AdminOrganization>[]>(
    () => [
      {
        key: "name",
        header: t("name"),
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
    <div className="space-y-6">
      {statsQuery.isLoading ? (
        <LoadingState variant="stats" rows={6} />
      ) : (
        <div className="grid gap-4 sm:grid-cols-2 lg:grid-cols-3">
          <StatCard
            label={t("totalUsers")}
            value={(stats?.total_users ?? 0).toLocaleString()}
            icon={Users}
          />
          <StatCard
            label={t("active24h")}
            value={(stats?.active_users_24h ?? 0).toLocaleString()}
            icon={Activity}
          />
          <StatCard
            label={t("organizations")}
            value={(stats?.total_organizations ?? 0).toLocaleString()}
            icon={Building2}
          />
          <StatCard
            label={t("agents")}
            value={(stats?.total_agents ?? 0).toLocaleString()}
            icon={Bot}
          />
          <StatCard
            label={t("conversations")}
            value={(stats?.total_conversations ?? 0).toLocaleString()}
            icon={MessageSquare}
          />
          <StatCard
            label={t("messages")}
            value={(stats?.total_messages ?? 0).toLocaleString()}
            icon={MessagesSquare}
          />
        </div>
      )}

      <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        <QuickLink
          href={ROUTES.ADMIN_USERS}
          icon={Users}
          title={t("manageUsers")}
          description={t("searchSuspendImpersonate")}
        />
        <QuickLink
          href={ROUTES.ADMIN_CONVERSATIONS}
          icon={MessageSquare}
          title={t("browseChats")}
          description={t("allConversationsAcrossUsers")}
        />
        <QuickLink
          href={ROUTES.ADMIN_SYSTEM}
          icon={Activity}
          title={t("systemHealth")}
          description={t("perServiceStatusUptime")}
        />
        <QuickLink
          href={ROUTES.ADMIN_RATINGS}
          icon={Star}
          title={t("responseRatings")}
          description={t("qualitySignalsFromUsers")}
        />
      </section>

      <ListCard
        title={t("organizations2")}
        counted={t("everyTenantDeploymentOnly")}
        contentClassName="p-0"
      >
        <DataTable<AdminOrganization>
          columns={orgColumns}
          rows={orgs}
          getRowKey={(org) => org.id}
          loading={orgs === undefined}
          skeletonRows={4}
          empty={t("noOrganizationsYet")}
          className="rounded-none border-0 bg-transparent [&_table]:min-w-[36rem]"
        />
      </ListCard>

      <ListCard
        title={t("recentActivity")}
        counted={t("workspaceWideEventsAcross")}
        contentClassName="p-0"
      >
        {events === undefined ? (
          <div className="p-5">
            <LoadingState variant="skeleton-list" rows={5} />
          </div>
        ) : events.length === 0 ? (
          <div className="text-muted-foreground px-5 py-12 text-center text-sm">
            {t("noRecentEvents")}
          </div>
        ) : (
          <ul className="divide-border divide-y">
            {events.map((e) => {
              const Icon = EVENT_ICON[e.type] ?? MessageSquare;
              return (
                <li key={e.id} className="flex items-center gap-3 px-5 py-3.5">
                  <span className="bg-muted text-muted-foreground inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg">
                    <Icon className="h-4 w-4" />
                  </span>
                  <div className="min-w-0 flex-1">
                    <p className="text-foreground truncate text-sm font-medium">{e.title}</p>
                    <p className="text-muted-foreground truncate text-xs">
                      {e.description}
                      {e.description && " · "}
                      {timeAgo(e.timestamp, tTime, locale)}
                    </p>
                  </div>
                </li>
              );
            })}
          </ul>
        )}
      </ListCard>
    </div>
  );
}

function QuickLink({
  href,
  icon: Icon,
  title,
  description,
}: {
  href: string;
  icon: LucideIcon;
  title: string;
  description: string;
}) {
  return (
    <Link
      href={href}
      className="border-border hover:border-foreground/30 hover:bg-accent bg-card group flex items-center gap-3 rounded-xl border p-4 transition-colors"
    >
      <span className="bg-muted text-foreground inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg">
        <Icon className="h-4 w-4" />
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-foreground text-sm font-semibold">{title}</p>
        <p className="text-muted-foreground truncate text-xs">{description}</p>
      </div>
      <ArrowUpRight className="text-muted-foreground h-4 w-4" />
    </Link>
  );
}
