"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  ArrowUpRight,
  Bot,
  Building2,
  MessageSquare,
  MessagesSquare,
  Users,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

import { StatCard } from "@/components/dashboard/stat-card";
import { LoadingState } from "@/components/states";
import { apiClient } from "@/lib/api-client";
import { ROUTES } from "@/lib/constants";
import { qk } from "@/lib/query-keys";
import { useTranslations } from "next-intl";

import type { AdminStats } from "@/types/admin";

/**
 * The deployment at a glance: six figures and the doors to the detail pages.
 *
 * Deliberately nothing else. The organizations table has a tab of its own, and
 * the "recent activity" feed left with it - a feed synthesized from the newest
 * conversations answered a question nobody was asking here, below figures that
 * already say how much is happening.
 */
export default function AdminOverviewPage() {
  const t = useTranslations("pages.admin");
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

  const stats = statsQuery.data;

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

      <section className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <QuickLink
          href={ROUTES.ADMIN_USERS}
          icon={Users}
          title={t("manageUsers")}
          description={t("searchSuspendImpersonate")}
        />
        <QuickLink
          href={ROUTES.ADMIN_ORGANIZATIONS}
          icon={Building2}
          title={t("organizations2")}
          description={t("everyTenantDeploymentOnly")}
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
      </section>
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
