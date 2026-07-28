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
 * - **The organization is first, and does not scroll.** Every agent, key and
 *   run below it is scoped by it, so the wrong one selected means every screen
 *   in the product is quietly the wrong screen. That control cannot be a small
 *   thing next to an avatar in a corner.
 * - **Search sits under it** rather than in the destination list: it is an
 *   action, not a place, and what it finds is scoped by the organization
 *   directly above it.
 * - **The destinations scroll on their own.** With enough entries the list has
 *   to move; the organization above and the account below must not move with
 *   it.
 * - **Language and theme are settings, not navigation** - two quiet icons in
 *   the footer, deliberately not shaped like the nav entries above them.
 * - **The account is last.** Least used, and where every comparable product
 *   puts it.
 *
 * It takes the nav as `children` so the desktop column and the slide-over pass
 * their own (the drawer needs its links to close it). Neither surface can end
 * up with controls the other lacks - the phone would lose the ability to switch
 * organization or sign out, and nobody reports that, because each surface looks
 * complete on its own.
 */

import type { ReactNode } from "react";

import { LanguageSwitcherIcon } from "@/components/language-switcher";
import { SidebarSearch } from "@/components/layout/sidebar-search";
import { SidebarUser } from "@/components/layout/sidebar-user";
import { OrgSwitcher } from "@/components/teams";
import { ThemeToggle } from "@/components/theme";

export function SidebarShell({ children }: { children: ReactNode }) {
  return (
    <>
      <div className="flex flex-col gap-1 px-3 py-3">
        <OrgSwitcher />
        <SidebarSearch />
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto">{children}</div>

      <div className="flex flex-col gap-1 border-t px-3 py-2">
        <div className="flex items-center">
          <LanguageSwitcherIcon />
          <ThemeToggle className="text-muted-foreground hover:text-foreground hover:bg-accent h-9 w-9 rounded-lg [&_svg]:size-[1.1rem]" />
        </div>
        <SidebarUser />
      </div>
    </>
  );
}
