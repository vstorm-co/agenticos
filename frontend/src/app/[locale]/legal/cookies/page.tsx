import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { CookiesBodyEn, CookiesBodyPl } from "@/components/legal/cookies-content";
import { LegalPage } from "@/components/legal/legal-page";
import type { Locale } from "@/i18n";
import { APP_NAME } from "@/lib/constants";
import { pageMetadata } from "@/lib/seo";

const LAST_UPDATED = "2026-05-08";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: Locale }>;
}): Promise<Metadata> {
  const t = await getTranslations("pages.meta");
  const { locale } = await params;
  return pageMetadata({
    title: t("cookiePolicy"),
    description: t("cookiesDescription", { app: APP_NAME }),
    path: "/legal/cookies",
    locale,
  });
}

export default async function CookiesPage({ params }: { params: Promise<{ locale: Locale }> }) {
  const { locale } = await params;
  const t = await getTranslations("legal.cookies");

  return (
    <LegalPage title={t("title")} summary={t("summary")} lastUpdated={LAST_UPDATED} locale={locale}>
      {locale === "pl" ? <CookiesBodyPl /> : <CookiesBodyEn />}
    </LegalPage>
  );
}
