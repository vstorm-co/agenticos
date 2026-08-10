"use client";

import type { ReactNode } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";

import { cn } from "@/lib/utils";

interface WidgetFrameProps {
  title: string;
  /** Route of the page that shows the whole answer; renders the corner link. */
  seeAll?: string;
  className?: string;
  children: ReactNode;
}

/**
 * The card shell every widget renders in: title, optional "see all" link,
 * body. `h-full` so a card stretched by a taller row sibling fills its cell
 * instead of leaving slack under the border.
 */
export function WidgetFrame({ title, seeAll, className, children }: WidgetFrameProps) {
  const t = useTranslations("dashboard");
  return (
    <section
      className={cn("border-border bg-card flex h-full flex-col rounded-xl border p-5", className)}
    >
      <div className="flex items-baseline justify-between gap-2 pb-3">
        <h3 className="text-foreground text-sm font-semibold tracking-tight">{title}</h3>
        {seeAll ? (
          <Link
            href={seeAll}
            className="text-muted-foreground hover:text-foreground shrink-0 text-xs"
          >
            {t("seeAll")}
          </Link>
        ) : null}
      </div>
      <div className="flex min-h-0 flex-1 flex-col">{children}</div>
    </section>
  );
}
