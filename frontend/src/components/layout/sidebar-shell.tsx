"use client";

/** Shared desktop and phone navigation chrome. Search stays above the scrollable
 * destinations; notifications and account stay within reach below them. */

import type { ReactNode } from "react";

import { NotificationBell } from "@/components/layout/notification-bell";
import { ServerSwitch } from "@/components/desktop/server-switch";
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

      <div
        className={cn(
          "flex flex-col gap-1 border-t py-2",
          collapsed ? "items-center px-1" : "px-3",
        )}
      >
        {collapsed ? (
          <div className="flex flex-col items-center gap-1">
            <SidebarSearch variant="icon" />
            <NotificationBell variant="icon" />
          </div>
        ) : (
          <NotificationBell variant="row" />
        )}
        <ServerSwitch compact={collapsed} />
        <SidebarUser compact={collapsed} />
      </div>
    </>
  );
}
