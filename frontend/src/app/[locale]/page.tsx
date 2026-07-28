import { redirect } from "next/navigation";

import { defaultLocale, type Locale } from "@/i18n";
import { ROUTES } from "@/lib/constants";

/**
 * AgenticOS is self-hosted — there is no public landing page, so the root is
 * just a door into the app.
 *
 * The redirect lives here rather than in the middleware or `next.config`
 * because only this route knows its locale: `next-intl` runs with
 * `localePrefix: "as-needed"`, so `/` is the default locale and `/pl` is
 * Polish, and the target has to keep whichever one the visitor arrived on.
 * Doing it in the middleware would mean re-deriving that from the pathname
 * before `next-intl` has resolved it; `next.config` redirects cannot see the
 * locale at all.
 *
 * The redirect is unconditional: every visitor lands on the sign-in form, and
 * signing in takes it from there.
 */
export default async function RootPage({ params }: { params: Promise<{ locale: Locale }> }) {
  const { locale } = await params;
  redirect(locale === defaultLocale ? ROUTES.LOGIN : `/${locale}${ROUTES.LOGIN}`);
}
