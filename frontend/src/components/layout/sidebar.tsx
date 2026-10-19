"use client";

/**
 * The same navigation, as a slide-over, for viewports too narrow to give a
 * column 240px and still have a page left.
 *
 * It renders `SidebarNav` inside `SidebarShell` rather than a list of its own.
 * The two drifted before - the drawer knew about Agents, Skills and Activity
 * while the top bar did not - and a phone offering destinations a desktop hides
 * is a bug nobody reports because each surface looks complete on its own. The
 * shell is here for the same reason: the organization switcher and the account
 * menu are no longer in a top bar to fall back on, so a phone without them
 * could not switch organization or sign out at all.
 */

import { SidebarNav } from "@/components/layout/app-sidebar";
import { SidebarShell } from "@/components/layout/sidebar-shell";
import { BrandMark } from "@/components/branding/brand-mark";
import { Sheet, SheetClose, SheetContent, SheetHeader, SheetTitle } from "@/components/ui";
import { useBranding } from "@/components/branding/branding-provider";
import { useSidebarStore } from "@/stores";

export function Sidebar() {
  const { appName } = useBranding();
  const { isOpen, close } = useSidebarStore();

  return (
    <Sheet open={isOpen} onOpenChange={close}>
      <SheetContent side="left" className="w-72 p-0">
        <SheetHeader className="h-14 shrink-0 px-4">
          {/* The mark beside the name, as the bar it slides over and the
              desktop column both draw it. */}
          <SheetTitle className="flex items-center gap-2 text-sm font-bold tracking-tight">
            <BrandMark />
            {appName}
          </SheetTitle>
          <SheetClose onClick={close} />
        </SheetHeader>
        <SidebarShell>
          <SidebarNav onNavigate={close} />
        </SidebarShell>
      </SheetContent>
    </Sheet>
  );
}
