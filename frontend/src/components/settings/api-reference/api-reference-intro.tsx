"use client";

import { BookOpen, Download } from "lucide-react";
import { useTranslations } from "next-intl";

import { DOCS } from "@/lib/constants";
import { Skeleton } from "@/components/ui/skeleton";
import { CopyCode } from "@/components/settings/copy-code";

/** What every call shares: where it goes, how it authenticates, and where to read more. */
export function ApiReferenceIntro({
  baseUrl,
  version,
}: {
  baseUrl: string;
  version: string | undefined;
}) {
  const t = useTranslations("apiReference");
  return (
    <section className="border-border bg-card space-y-4 rounded-xl border px-5 py-4">
      <div className="space-y-1">
        <h2 className="text-sm font-semibold">{t("title")}</h2>
        {version === undefined ? (
          <Skeleton className="h-4 w-64 max-w-full" />
        ) : (
          <p className="text-muted-foreground text-xs">{t("description", { version })}</p>
        )}
      </div>
      <div className="grid gap-4 md:grid-cols-2">
        <div className="space-y-1.5">
          <h3 className="text-xs font-semibold">{t("baseUrl")}</h3>
          <CopyCode code={baseUrl} />
        </div>
        <div className="space-y-1.5">
          <h3 className="text-xs font-semibold">{t("authTitle")}</h3>
          <p className="text-muted-foreground text-xs leading-relaxed">
            {t.rich("authBody", {
              code: (chunks) => (
                <code className="bg-muted rounded px-1 py-0.5 font-mono">{chunks}</code>
              ),
            })}
          </p>
        </div>
      </div>
      <div className="flex flex-wrap gap-x-4 gap-y-1 text-xs">
        <a
          href={DOCS.API_KEYS}
          target="_blank"
          rel="noreferrer"
          className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1 underline underline-offset-2"
        >
          <BookOpen className="h-3.5 w-3.5" aria-hidden />
          {t("guide")}
        </a>
        <a
          href="/api/public/openapi.json"
          download="agenticos-openapi.json"
          className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1 underline underline-offset-2"
        >
          <Download className="h-3.5 w-3.5" aria-hidden />
          {t("download")}
        </a>
      </div>
    </section>
  );
}
