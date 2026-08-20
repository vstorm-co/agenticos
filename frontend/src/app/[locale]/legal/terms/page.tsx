import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { LegalPage } from "@/components/legal/legal-page";
import { TermsBodyEn, TermsBodyPl } from "@/components/legal/terms-content";
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
    title: t("termsOfService"),
    description: t("termsDescription", { app: appName }),
    path: "/legal/terms",
    locale,
  });
}

export default async function TermsPage({ params }: { params: Promise<{ locale: Locale }> }) {
  const { locale } = await params;
  const { appName } = await readBranding();
  const t = await getTranslations("legal.terms");

  return (
    <LegalPage
      title={t("title")}
      summary={t("summary", { appName })}
      lastUpdated={LAST_UPDATED}
      locale={locale}
    >
      {locale === "pl" ? <TermsBodyPl appName={appName} /> : <TermsBodyEn appName={appName} />}
    </LegalPage>
  );
}
