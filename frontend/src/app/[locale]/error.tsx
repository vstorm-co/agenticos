"use client";

import { useEffect } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";

import { Button } from "@/components/ui/button";
import { ROUTES } from "@/lib/constants";
import { useTranslations } from "next-intl";

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  const t = useTranslations("pages.root");
  const router = useRouter();

  useEffect(() => {
    console.error("Page error:", error);
  }, [error]);

  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center px-4 text-center">
      <p className="text-destructive text-sm font-semibold tracking-wider uppercase">
        {t("error")}
      </p>
      <h1 className="text-foreground mt-2 text-2xl font-bold tracking-tight sm:text-3xl">
        {t("somethingWentWrong")}
      </h1>
      <p className="text-muted-foreground mt-3 max-w-md">{t("errorOccurredWhileLoading")}</p>
      {error.digest && (
        <p className="text-muted-foreground/60 mt-1 text-xs">Error ID: {error.digest}</p>
      )}
      <div className="mt-6 flex flex-wrap items-center justify-center gap-3">
        <Button onClick={reset}>{t("tryAgain")}</Button>
        <Button variant="secondary" onClick={() => router.back()}>
          {t("goBack")}
        </Button>
        <Button variant="outline" asChild>
          <Link href={ROUTES.DASHBOARD}>{t("dashboard")}</Link>
        </Button>
      </div>
    </div>
  );
}
