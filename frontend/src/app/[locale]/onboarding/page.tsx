import { getTranslations } from "next-intl/server";
import type { Metadata } from "next";

import { OnboardingPlaceholder } from "@/components/onboarding/onboarding-placeholder";
import type { Locale } from "@/i18n";
import { readBranding } from "@/lib/branding-server";
import { pageMetadata } from "@/lib/seo";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: Locale }>;
}): Promise<Metadata> {
  const t = await getTranslations("pages.root");
  const { locale } = await params;
  const { appName } = await readBranding();
  return pageMetadata({
    brand: appName,
    title: t("onboardingTitle"),
    description: t("onboardingDescription"),
    path: "/onboarding",
    locale,
    noindex: true,
  });
}

export default function OnboardingPage() {
  return <OnboardingPlaceholder />;
}
