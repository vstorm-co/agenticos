"use client";

/** Shared desktop and phone navigation chrome. Organization selection and search
 * stay above the scrollable destinations; notifications and account stay below. */

import Link from "next/link";
import { SquarePen } from "lucide-react";
import { useTranslations } from "next-intl";
import type { ReactNode } from "react";

import { DesktopInstallPrompt } from "@/components/layout/desktop-install-prompt";
import { ConsoleVersion } from "@/components/layout/console-version";

import { NotificationBell } from "@/components/layout/notification-bell";
import { SidebarSearch } from "@/components/layout/sidebar-search";
import { SidebarUser } from "@/components/layout/sidebar-user";
import { OrganizationSwitcher } from "@/components/layout/organization-switcher";
import { buttonVariants } from "@/components/ui/button";
import { cn } from "@/lib/utils";

export function SidebarShell({
  children,
  collapsed = false,
  onNavigate,
}: {
  children: ReactNode;
  collapsed?: boolean;
  onNavigate?: () => void;
}) {
  const t = useTranslations("workspaceHome");
  return (
    <>
      <div className={cn("shrink-0 pt-1", collapsed ? "flex justify-center px-1 pb-2" : "px-3")}>
        <OrganizationSwitcher collapsed={collapsed} onNavigate={onNavigate} />
      </div>
      {!collapsed && (
        <div className="flex shrink-0 flex-col gap-2 px-3 pt-3 pb-3">
          <Link
            href="/chat?new=workspace"
            onClick={onNavigate}
            className={cn(buttonVariants(), "w-full justify-start gap-2.5 rounded-xl px-3")}
            data-tour="chat-start"
          >
            <SquarePen className="size-4" aria-hidden />
            {t("newChat")}
          </Link>
          <SidebarSearch variant="row" />
        </div>
      )}
      <div className="flex min-h-0 flex-1 scrollbar-thin flex-col overflow-y-auto overscroll-contain">
        {children}
      </div>

      {!collapsed && <DesktopInstallPrompt />}
      <div className={cn("flex flex-col gap-1 py-2", collapsed ? "items-center px-1" : "px-3")}>
        {/* The language and the theme used to be
            here too, which filed "set this once" beside "find something" under
            four unlabelled glyphs; they are named rows in the account menu
            below now. */}
        <div className={cn("flex items-center gap-0.5", collapsed && "flex-col")}>
          {collapsed && <SidebarSearch variant="icon" />}
          <NotificationBell variant="icon" />
          <ConsoleVersion collapsed={collapsed} />
        </div>
        <SidebarUser compact={collapsed} />
      </div>
    </>
  );
}
