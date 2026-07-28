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
  const { locale } = await params;
  return pageMetadata({
    title: "Get started",
    description: "Set up your workspace.",
    path: "/onboarding",
    locale,
    noindex: true,
  });
}

export default function OnboardingPage() {
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
            title="Onboarding is under construction"
            description="The setup wizard is being rebuilt. Nothing is blocking you - head into the workspace and start from there."
            cta={{ label: "Go to dashboard", href: ROUTES.DASHBOARD }}
            secondaryCta={{ label: "Start a chat", href: ROUTES.CHAT }}
            className="w-full"
          />
        </main>
      </div>
    </AuthGuard>
  );
}
