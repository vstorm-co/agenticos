import { getTranslations } from "next-intl/server";
import { useTranslations } from "next-intl";
import type { Metadata } from "next";
import { Construction } from "lucide-react";

import { AuthGuard } from "@/components/layout/auth-guard";
import { EmptyState } from "@/components/states";
import type { Locale } from "@/i18n";
import { APP_NAME, ROUTES } from "@/lib/constants";
import { pageMetadata } from "@/lib/seo";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: Locale }>;
}): Promise<Metadata> {
  const t = await getTranslations("pages.root");
  const { locale } = await params;
  return pageMetadata({
    title: t("onboardingTitle"),
    description: t("onboardingDescription"),
    path: "/onboarding",
    locale,
    noindex: true,
  });
}

export default function OnboardingPage() {
  const t = useTranslations("pages.root");
  return (
    <AuthGuard>
      <div className="bg-background text-foreground flex min-h-screen flex-col">
        <header className="border-border border-b">
          <div className="mx-auto flex max-w-3xl items-center px-6 py-4">
            <span className="text-foreground inline-flex items-center gap-2 text-base font-semibold tracking-tight">
              <span aria-hidden className="bg-brand inline-block h-2.5 w-2.5 rounded-full" />
              {APP_NAME}
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
