import Link from "next/link";
import type { ReactNode } from "react";
import { getTranslations } from "next-intl/server";

import type { Locale } from "@/i18n";
import { APP_NAME, ROUTES } from "@/lib/constants";

interface LegalPageProps {
  title: string;
  summary?: string;
  /** ISO date string of last update - e.g. "2026-05-08". */
  lastUpdated: string;
  /** Locale for date formatting + see-also labels. */
  locale: Locale;
  children: ReactNode;
}

/**
 * Shell for the three legal documents - the only pages a deployment serves to
 * signed-out visitors. Deliberately plain: no nav, no footer sitemap, nothing
 * to click but the sibling documents and the way back into the app.
 */
export async function LegalPage({ title, summary, lastUpdated, locale, children }: LegalPageProps) {
  const t = await getTranslations("legal");

  const related = [
    { label: t("terms.title"), href: ROUTES.LEGAL_TERMS },
    { label: t("privacy.title"), href: ROUTES.LEGAL_PRIVACY },
    { label: t("cookies.title"), href: ROUTES.LEGAL_COOKIES },
  ];

  return (
    <div className="theme-light bg-background text-foreground min-h-screen">
      <header className="border-foreground/10 border-b">
        <div className="mx-auto flex h-16 max-w-3xl items-center px-6">
          <Link
            href={ROUTES.HOME}
            className="text-foreground inline-flex items-center gap-2 text-base font-bold tracking-tight"
          >
            <span aria-hidden className="bg-brand inline-block h-2.5 w-2.5 rounded-full" />
            {APP_NAME}
          </Link>
        </div>
      </header>

      <main id="main" className="mx-auto max-w-3xl px-6 pt-16 pb-24">
        <span className="eyebrow-badge mb-6">{t("eyebrow")}</span>
        <h1 className="text-display-lg mb-5">{title}</h1>
        {summary && <p className="text-foreground/70 text-lg leading-relaxed">{summary}</p>}
        <p className="text-foreground/50 mt-6 font-mono text-xs tracking-wider uppercase">
          {t("lastUpdated", { date: formatDate(lastUpdated, locale) })}
        </p>

        <article className="prose-legal mt-16">{children}</article>

        <nav className="border-foreground/10 mt-16 flex flex-wrap items-center gap-3 border-t pt-8">
          <p className="text-foreground/45 font-mono text-[11px] tracking-wider uppercase">
            {t("seeAlso")}
          </p>
          {related.map((r) => (
            <Link
              key={r.href}
              href={r.href}
              className="border-foreground/15 hover:border-foreground/40 text-foreground/70 hover:text-foreground inline-flex rounded-full border px-3 py-1 text-xs font-medium transition-colors"
            >
              {r.label}
            </Link>
          ))}
        </nav>
      </main>
    </div>
  );
}

function formatDate(iso: string, locale: Locale): string {
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  return d.toLocaleDateString(locale === "pl" ? "pl-PL" : "en-US", {
    year: "numeric",
    month: "long",
    day: "numeric",
  });
}
