import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { RegisterForm } from "@/components/auth";
import type { Locale } from "@/i18n";
import { readBranding } from "@/lib/branding-server";
import { pageMetadata } from "@/lib/seo";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: Locale }>;
}): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations("pages.meta");
  const { appName } = await readBranding();
  return pageMetadata({
    brand: appName,
    title: t("registerTitle"),
    description: t("registerDescription"),
    path: "/register",
    locale,
  });
}

export default function RegisterPage() {
  return <RegisterForm />;
}
