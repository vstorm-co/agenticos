"use client";

import { useTranslations } from "next-intl";
import { Construction } from "lucide-react";

import { useBranding } from "@/components/branding/branding-provider";
import { AuthGuard } from "@/components/layout/auth-guard";
import { EmptyState } from "@/components/states";
import { ROUTES } from "@/lib/constants";

/**
 * What `/onboarding` shows while the flow is rebuilt.
 *
 * A client component because `EmptyState` takes its icon as a component, which a
 * server component cannot hand across: the page rendered it from the server and
 * every visit ended in the error boundary.
 */
export function OnboardingPlaceholder() {
  const t = useTranslations("pages.root");
  const { appName } = useBranding();
  return (
    <AuthGuard>
      <div className="bg-background text-foreground flex min-h-screen flex-col">
        <header className="border-border border-b">
          <div className="mx-auto flex max-w-3xl items-center px-6 py-4">
            <span className="text-foreground inline-flex items-center gap-2 text-base font-semibold tracking-tight">
              <span aria-hidden className="bg-brand inline-block h-2.5 w-2.5 rounded-full" />
              {appName}
            </span>
          </div>
        </header>

        <main className="mx-auto flex w-full max-w-3xl flex-1 items-center px-6 py-12">
          <EmptyState
            icon={Construction}
            title={t("onboardingUnderConstruction")}
            description={t("onboardingRebuilt")}
            cta={{ label: t("goToDashboard"), href: ROUTES.DASHBOARD }}
            secondaryCta={{ label: t("startAChat"), href: ROUTES.CHAT }}
            className="w-full"
          />
        </main>
      </div>
    </AuthGuard>
  );
}
