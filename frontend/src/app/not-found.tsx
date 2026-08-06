import Link from "next/link";

import { Button } from "@/components/ui/button";
import { NotFoundBackButton } from "@/components/layout/not-found-back-button";
import { ROUTES } from "@/lib/constants";
import { useTranslations } from "next-intl";

export default function NotFound() {
  const t = useTranslations("pages.root");
  return (
    <div className="bg-background flex min-h-screen flex-col items-center justify-center px-4 text-center">
      <p className="text-brand text-sm font-semibold tracking-wider uppercase">404</p>
      <h1 className="text-foreground mt-2 text-4xl font-bold tracking-tight sm:text-5xl">
        {t("pageNotFound")}
      </h1>
      <p className="text-muted-foreground mt-4">{t("pageMissingOrMoved")}</p>
      <div className="mt-8 flex flex-wrap items-center justify-center gap-3">
        <Button asChild>
          <Link href={ROUTES.DASHBOARD}>{t("dashboardLink")}</Link>
        </Button>
        <NotFoundBackButton />
      </div>
    </div>
  );
}
