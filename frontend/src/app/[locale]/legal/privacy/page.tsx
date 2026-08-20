import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { PrivacyBodyEn, PrivacyBodyPl } from "@/components/legal/privacy-content";
import { LegalPage } from "@/components/legal/legal-page";
import type { Locale } from "@/i18n";
import { readBranding } from "@/lib/branding-server";
import { pageMetadata } from "@/lib/seo";

const LAST_UPDATED = "2026-05-08";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: Locale }>;
}): Promise<Metadata> {
  const t = await getTranslations("pages.meta");
  const { locale } = await params;
  const { appName } = await readBranding();
  return pageMetadata({
    brand: appName,
    title: t("privacyPolicy"),
    description: t("privacyDescription", { app: appName }),
    path: "/legal/privacy",
    locale,
  });
}

export default async function PrivacyPage({ params }: { params: Promise<{ locale: Locale }> }) {
  const { locale } = await params;
  const { appName } = await readBranding();
  const t = await getTranslations("legal.privacy");

  return (
    <LegalPage
      title={t("title")}
      summary={t("summary", { appName })}
      lastUpdated={LAST_UPDATED}
      locale={locale}
    >
      {locale === "pl" ? <PrivacyBodyPl appName={appName} /> : <PrivacyBodyEn appName={appName} />}
    </LegalPage>
  );
}
