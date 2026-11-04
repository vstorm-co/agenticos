"use client";

/** Shared desktop and phone navigation chrome. Search stays above the scrollable
 * destinations; notifications and account stay within reach below them. */

import type { ReactNode } from "react";

import { DesktopInstallPrompt } from "@/components/layout/desktop-install-prompt";
import { ConsoleVersion } from "@/components/layout/console-version";

import { NotificationBell } from "@/components/layout/notification-bell";
import { SidebarSearch } from "@/components/layout/sidebar-search";
import { SidebarUser } from "@/components/layout/sidebar-user";
import { cn } from "@/lib/utils";

export function SidebarShell({
  children,
  collapsed = false,
}: {
  children: ReactNode;
  collapsed?: boolean;
}) {
  return (
    <>
      {!collapsed && (
        <div className="shrink-0 px-3 pt-3">
          <SidebarSearch variant="row" />
        </div>
      )}
      <div className="min-h-0 flex-1 scrollbar-thin overflow-y-auto overscroll-contain">
        {children}
      </div>

      {!collapsed && <DesktopInstallPrompt />}
      <div
        className={cn(
          "flex flex-col gap-1 border-t py-2",
          collapsed ? "items-center px-1" : "px-3",
        )}
      >
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
