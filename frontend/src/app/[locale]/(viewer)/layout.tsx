import { DeploymentGate } from "@/components/branding/deployment-gate";
import { ActiveOrgGuard } from "@/components/layout/active-org-guard";
import { AuthGuard } from "@/components/layout/auth-guard";
import { ImpersonationBanner } from "@/components/layout/impersonation-banner";

/**
 * A signed-in page that is the whole window, with none of the console around it.
 *
 * An artifact is a page somebody opens to read, the way they would open its
 * public link - so the sidebar, the tab bar and the page padding of
 * `(dashboard)` would only shrink it. What stays is what decides whether it may
 * be shown at all: the session, the active organization every request is scoped
 * to, the maintenance gate, and the strip saying this browser is acting as
 * somebody else, which must never be hidden by a page that fills the screen.
 */
export default function ViewerLayout({ children }: { children: React.ReactNode }) {
  return (
    <AuthGuard>
      <ActiveOrgGuard />
      <div className="bg-background flex h-dvh flex-col">
        <ImpersonationBanner />
        <main id="main" tabIndex={-1} className="flex min-h-0 flex-1 flex-col">
          <DeploymentGate>{children}</DeploymentGate>
        </main>
      </div>
    </AuthGuard>
  );
}
