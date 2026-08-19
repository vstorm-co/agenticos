import type { Metadata } from "next";
import Link from "next/link";

import { ResetPasswordForm } from "@/components/auth/reset-password-form";
import type { Locale } from "@/i18n";
import { ROUTES } from "@/lib/constants";
import { readBranding } from "@/lib/branding-server";
import { pageMetadata } from "@/lib/seo";

import { getTranslations } from "next-intl/server";
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
    title: t("resetPasswordTitle"),
    description: t("resetPasswordDescription"),
    path: "/reset-password",
    locale,
    noindex: true,
  });
}

interface PageProps {
  searchParams: Promise<{ token?: string }>;
}

export default async function ResetPasswordPage({ searchParams }: PageProps) {
  const t = await getTranslations("pages.auth");
  const { token } = await searchParams;

  if (!token) {
    return (
      <div className="space-y-6">
        <div className="space-y-2">
          <span className="eyebrow text-foreground/55">{t("resetPassword")}</span>
          <h1 className="text-display-md text-foreground">{t("missingExpiredLink")}</h1>
          <p className="text-foreground/70 text-sm">{t("pageExpectsTokenFrom")}</p>
        </div>
        <Link
          href={ROUTES.FORGOT_PASSWORD}
          className="bg-foreground text-background hover:bg-foreground/90 inline-flex h-11 items-center justify-center gap-2 rounded-full px-5 text-sm font-medium transition-colors"
        >
          {t("requestNewLink")}
        </Link>
        <p className="text-foreground/55 text-xs">
          {t.rich("orReturnToSignIn", {
            link: (chunks) => (
              <Link
                href={ROUTES.LOGIN}
                className="text-foreground hover:text-foreground/80 underline-offset-4 hover:underline"
              >
                {chunks}
              </Link>
            ),
          })}
        </p>
      </div>
    );
  }

  return <ResetPasswordForm token={token} />;
}
