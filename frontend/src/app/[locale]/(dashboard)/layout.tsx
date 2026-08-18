import { CustomIconsProvider } from "@/components/icons/custom-icons";
import { MobileHeader, Sidebar } from "@/components/layout";
import { ActiveOrgGuard } from "@/components/layout/active-org-guard";
import { AppSidebar } from "@/components/layout/app-sidebar";
import { AuthGuard } from "@/components/layout/auth-guard";
import { CommandPalette } from "@/components/layout/command-palette";
import { MobileTabBar } from "@/components/layout/mobile-tab-bar";
import { PageTransition } from "@/components/layout/page-transition";
import { OnboardingFlows } from "@/components/onboarding/onboarding-flows";
import { OnboardingTour } from "@/components/onboarding/onboarding-tour";

export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  return (
    <AuthGuard>
      {/* An organization the server refuses is not a page-level problem: it
          empties every permission-gated destination at once, so the recovery
          lives beside the navigation it would otherwise silently strip. */}
      <ActiveOrgGuard />
      {/* Which custom brand marks the deployment ships - fetched once here so
          every icon down the tree reads it from context instead of querying. */}
      <CustomIconsProvider>
        <div className="flex h-screen flex-col">
          {/* The fixed accent wash every translucent surface frosts - see
              .ambient-backdrop in globals.css for why a sidebar needs one. */}
          <div aria-hidden className="ambient-backdrop" />
          {/* Nothing above `md`: the brand, the organization, search, settings
            and the account are all in the column now, and this renders only
            where the column is a slide-over that needs opening. */}
          <MobileHeader />
          {/* The column and the content scroll independently, which is the point
            of a persistent sidebar: navigation stays put while a long run list
            moves under it. */}
          <div className="flex min-h-0 flex-1">
            <AppSidebar />
            {/* `relative` is load-bearing, and not for anything it positions.
                An absolutely positioned descendant with no positioned ancestor
                resolves against the initial containing block, and its layout
                overflow then inflates the *document's* scrollable rect: measured
                on the agent Builder, `documentElement.scrollHeight` read 3130
                against a 1290 viewport while the document could not be scrolled
                by a pixel. Chrome draws a scrollbar track for that - inert, with
                a full-height thumb - so anybody whose macOS shows scrollbars
                always saw two bars side by side and one of them did nothing. The
                offenders are the hidden inputs Radix's Select renders. Contained
                here, `scrollHeight` is the viewport's own 1290.

                `relative` rather than `contain: paint`, which fixes it equally
                and would also make this the containing block for every `fixed`
                descendant - the chat's sources panel and two drop overlays are
                `fixed` and rendered inline, so containment would move them. */}
            <main
              id="main"
              tabIndex={-1}
              className="relative flex min-h-0 flex-1 flex-col overflow-auto px-3 pt-4 pb-20 sm:px-6 sm:pt-8 lg:pb-16"
            >
              <PageTransition>{children}</PageTransition>
            </main>
          </div>
          <Sidebar />
          <MobileTabBar />
          <CommandPalette />
          <OnboardingTour />
          <OnboardingFlows />
        </div>
      </CustomIconsProvider>
    </AuthGuard>
  );
}
