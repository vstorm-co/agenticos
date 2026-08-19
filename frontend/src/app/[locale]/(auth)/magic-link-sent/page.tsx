import type { Metadata } from "next";
import Link from "next/link";
import { ArrowLeft, Mail } from "lucide-react";

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
    title: t("magicLinkSentTitle"),
    description: t("magicLinkSentDescription"),
    path: "/magic-link-sent",
    locale,
    noindex: true,
  });
}

interface PageProps {
  searchParams: Promise<{ email?: string }>;
}

export default async function MagicLinkSentPage({ searchParams }: PageProps) {
  const t = await getTranslations("pages.auth");
  const { email } = await searchParams;

  return (
    <div className="space-y-8 text-center">
      <div
        className="bg-brand/15 mx-auto flex h-16 w-16 items-center justify-center rounded-full"
        style={{ boxShadow: "0 0 40px oklch(from var(--color-brand) l c h / 0.4)" }}
      >
        <Mail className="text-foreground h-7 w-7" />
      </div>

      <div className="space-y-2">
        <span className="eyebrow text-foreground/55">{t("magicLink")}</span>
        <h1 className="text-display-md text-foreground [&_em]:font-normal [&_em]:italic">
          {t.rich("inboxIncoming", { em: (chunks) => <em>{chunks}</em> })}
        </h1>
        <p className="text-foreground/70 text-sm">
          {email
            ? t.rich("magicLinkSentTo", {
                email,
                strong: (chunks) => <span className="text-foreground font-medium">{chunks}</span>,
              })
            : t("magicLinkSent")}
        </p>
      </div>

      <div className="border-foreground/10 bg-foreground/[0.03] rounded-2xl border px-5 py-4 text-left">
        <p className="text-foreground/70 text-xs leading-relaxed">
          {t.rich("checkSpamFolder", {
            link: (chunks) => (
              <Link
                href={ROUTES.LOGIN}
                className="text-foreground hover:text-foreground/80 font-medium underline-offset-4 hover:underline"
              >
                {chunks}
              </Link>
            ),
          })}
        </p>
      </div>

      <Link
        href={ROUTES.LOGIN}
        className="text-foreground/55 hover:text-foreground inline-flex items-center gap-2 text-sm font-medium"
      >
        <ArrowLeft className="h-4 w-4" />
        {t("backSign")}
      </Link>
    </div>
  );
}
