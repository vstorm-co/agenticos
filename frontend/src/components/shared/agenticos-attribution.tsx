"use client";

import { ArrowUpRight } from "lucide-react";
import { useTranslations } from "next-intl";

import { BrandIcon } from "@/components/icons/brand-icon";
import { Button } from "@/components/ui/button";
import { LOGO_DATA_URI } from "@/lib/logo.generated";

/** A floating discovery badge; the document and its downloads stay intact. */
export function AgenticosAttribution({ visible = true }: { visible?: boolean }) {
  const t = useTranslations("sharedAttribution");
  if (!visible) return null;
  return (
    <footer className="bg-card/95 border-foreground/10 pointer-events-auto flex w-fit max-w-full shrink-0 items-center justify-between gap-3 rounded-2xl border p-2.5 shadow-lg backdrop-blur-md sm:gap-4 sm:p-3">
      <div className="flex min-w-0 items-center gap-2.5 sm:gap-3">
        {/* Always the AgenticOS mark: a deployment may have its own branding. */}
        {/* eslint-disable-next-line @next/next/no-img-element -- the canonical generated SVG, already shared with the sidebar and favicon */}
        <img
          src={LOGO_DATA_URI}
          alt=""
          width={36}
          height={36}
          className="size-8 shrink-0 sm:size-9"
        />
        <div className="min-w-0 space-y-0.5">
          <p className="text-foreground text-xs sm:text-sm">
            {t.rich("madeWith", {
              name: (chunks) => <span className="font-semibold">{chunks}</span>,
            })}
          </p>
          <p className="text-muted-foreground text-[11px] leading-4 sm:text-xs">
            {t("description")}
          </p>
        </div>
      </div>
      <Button
        variant="secondary"
        asChild
        className="min-h-11 shrink-0 gap-1.5 px-3 text-xs sm:gap-2 sm:text-sm"
      >
        <a
          href="https://github.com/vstorm-co/agenticos"
          target="_blank"
          rel="noopener noreferrer"
          referrerPolicy="no-referrer"
        >
          <BrandIcon name="github" aria-hidden />
          <span className="hidden sm:inline">{t("cta")}</span>
          <span className="sm:hidden">{t("ctaShort")}</span>
          <ArrowUpRight className="hidden sm:block" aria-hidden />
        </a>
      </Button>
    </footer>
  );
}
