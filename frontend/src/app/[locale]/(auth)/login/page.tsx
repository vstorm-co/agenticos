import type { Metadata } from "next";
import { getTranslations } from "next-intl/server";

import { LoginForm } from "@/components/auth";
import type { Locale } from "@/i18n";
import { pageMetadata } from "@/lib/seo";

export async function generateMetadata({
  params,
}: {
  params: Promise<{ locale: Locale }>;
}): Promise<Metadata> {
  const { locale } = await params;
  const t = await getTranslations("pages.meta");
  return pageMetadata({
    title: t("loginTitle"),
    description: t("loginDescription"),
    path: "/login",
    locale,
    noindex: true,
  });
}

export default function LoginPage() {
  return <LoginForm />;
}
