import Link from "next/link";

import { Button } from "@/components/ui/button";
import { NotFoundBackButton } from "@/components/layout/not-found-back-button";
import { ROUTES } from "@/lib/constants";

/**
 * The 404 page.
 *
 * Its copy is English in the file, deliberately. This is the *root*
 * `not-found`, so it renders under `app/layout.tsx` and never under
 * `NextIntlClientProvider`, which lives one level down in
 * `[locale]/layout.tsx`. A translator here throws for want of that context,
 * and the 404 it was rendering answers 500 instead - as `global-error.tsx`,
 * outside the provider for the same reason, already knows.
 */
export default function NotFound() {
  return (
    <div className="bg-background flex min-h-screen flex-col items-center justify-center px-4 text-center">
      <p className="text-brand text-sm font-semibold tracking-wider uppercase">404</p>
      <h1 className="text-foreground mt-2 text-4xl font-bold tracking-tight sm:text-5xl">
        {t("pageNotFound")}
      </h1>
      <p className="text-muted-foreground mt-4">{t("pageMissingOrMoved")}</p>
      <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
        <Button asChild>
          {/* i18n-exempt: rendered outside NextIntlClientProvider - see the docstring */}
          <Link href={ROUTES.DASHBOARD}>Dashboard</Link>
        </Button>
        <NotFoundBackButton />
      </div>
    </div>
  );
}
