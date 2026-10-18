"use client";

import Link from "next/link";
import { BookOpen, Braces } from "lucide-react";
import { useTranslations } from "next-intl";

import { usePublicConfig } from "@/components/public-config/public-config-provider";
import { CopyCode } from "@/components/settings/copy-code";
import { Button } from "@/components/ui";
import { DOCS, ROUTES } from "@/lib/constants";

/** Where the API is, how a key authenticates, and the two places that say what it can do. */
export function ApiUsage() {
  const t = useTranslations("apiUsage");
  const { apiUrl } = usePublicConfig();
  return (
    <section className="border-border bg-card rounded-xl border" data-tour="api-usage">
      <header className="border-border border-b px-5 py-4">
        <h2 className="text-foreground text-sm font-semibold">{t("title")}</h2>
        <p className="text-muted-foreground mt-1 text-xs">{t("why")}</p>
      </header>
      <div className="grid gap-4 px-5 py-5 md:grid-cols-2">
        <div className="space-y-1.5">
          <h3 className="text-xs font-semibold">{t("baseUrl")}</h3>
          <CopyCode code={apiUrl} />
          <p className="text-muted-foreground text-xs">
            {t.rich("auth", {
              code: (chunks) => (
                <code className="bg-muted rounded px-1 py-0.5 font-mono">{chunks}</code>
              ),
            })}
          </p>
        </div>
        <div className="flex flex-col items-start gap-2 md:justify-center">
          <Button asChild size="sm">
            <Link href={ROUTES.SETTINGS_API_REFERENCE}>
              <Braces className="h-4 w-4" aria-hidden />
              {t("reference")}
            </Link>
          </Button>
          <a
            href={DOCS.API_KEYS}
            target="_blank"
            rel="noreferrer"
            className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1 text-xs underline underline-offset-2"
          >
            <BookOpen className="h-3.5 w-3.5" aria-hidden />
            {t("guide")}
          </a>
        </div>
      </div>
    </section>
  );
}
