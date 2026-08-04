"use client";

import { useEffect } from "react";

import { ErrorState } from "@/components/states";
import { useTranslations } from "next-intl";

export default function DashboardError({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  const t = useTranslations("pages.root");
  useEffect(() => {
    console.error("Dashboard error:", error); // i18n-exempt: a log line, read in a console
  }, [error]);

  return (
    <div className="flex min-h-0 flex-1 items-center justify-center py-10">
      <ErrorState
        className="w-full max-w-md"
        title={t("sectionFailed")}
        description={
          error.digest
            ? t("unexpectedWithDigest", { digest: error.digest })
            : t("unexpectedWhileLoading")
        }
        cta={{ label: t("tryAgain"), onClick: () => reset() }}
      />
    </div>
  );
}
