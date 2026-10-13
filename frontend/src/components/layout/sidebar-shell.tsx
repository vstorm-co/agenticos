"use client";

/**
 * Everything in the column that is not a destination.
 *
 * The top bar used to hold search, language, theme, the organization and the
 * account. It is gone above `md`: with those five moved here it held a logo,
 * and 56px of nothing across every page is a page's worth of screen given away
 * over a session. What is left of it (`MobileHeader`) exists only where the
 * column is a slide-over and something has to open it.
 *
 * The order is not arbitrary:
 *
 * - **Search and the bell are the footer's actions**, and the only things in
 *   that row. It held four icons: those two plus the language and the theme,
 *   which put "find anything in this organization" beside "switch to German"
 *   under four unlabelled glyphs. Both settings are named rows in the account
 *   menu now, where somebody looks for a preference.
 * - **The destinations are the whole middle.** Nothing sits above them: the
 *   organization moved into the account's menu, where "who am I and where am
 *   I" is one question with one answer instead of two controls at opposite
 *   ends of the sidebar.
 * - **The account is last.** Least used, and where every comparable product
 *   puts it. The control that collapses the column is not here at all: it sits
 *   on the column's own title bar beside the brand (`AppSidebar`), which is
 *   where a collapsible panel's handle belongs.
 *
 * It takes the nav as `children` so the desktop column and the slide-over pass
 * their own (the drawer needs its links to close it). Neither surface can end
 * up with controls the other lacks - the phone would lose the ability to switch
 * organization or sign out, and nobody reports that, because each surface looks
 * complete on its own.
 *
 * `collapsed` is the desktop rail only. The slide-over never passes it: a
 * drawer somebody deliberately opened has the width, and a rail inside one
 * would be 56px of icons floating in a 288px sheet.
 */

import type { ReactNode } from "react";

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
      <div className="min-h-0 flex-1 scrollbar-thin overflow-y-auto">{children}</div>

      <div
        className={cn(
          "flex flex-col gap-1 border-t py-2",
          collapsed ? "items-center px-1" : "px-3",
        )}
      >
        {/* Two actions, and only actions. The language and the theme used to be
            here too, which filed "set this once" beside "find something" under
            four unlabelled glyphs; they are named rows in the account menu
            below now. */}
        <div className={cn("flex items-center gap-0.5", collapsed && "flex-col")}>
          <SidebarSearch variant="icon" />
          <NotificationBell variant="icon" />
        </div>
        <SidebarUser compact={collapsed} />
      </div>
    </>
  );
}
