import Link from "next/link";
import { ChevronRight } from "lucide-react";
import type { ReactNode } from "react";

import { RestartTourButton } from "@/components/onboarding/restart-tour-button";
import { cn } from "@/lib/utils";
import { useTranslations } from "next-intl";

export interface Crumb {
  label: string;
  href?: string;
}

interface PageHeaderProps {
  title: ReactNode;
  description?: ReactNode;
  /** Breadcrumb trail (last item is the current page; omit href on it). */
  breadcrumbs?: Crumb[];
  /** Right-aligned actions (buttons, etc.). */
  actions?: ReactNode;
  /** State of the thing on the page (status pills), set above the actions. */
  badges?: ReactNode;
  className?: string;
}

/**
 * The single page-header used across the whole dashboard. Keeps title/description/
 * actions/breadcrumbs consistent and theme-aware. Replaces ad-hoc per-page heroes.
 */
export function PageHeader({
  title,
  description,
  breadcrumbs,
  actions,
  badges,
  className,
}: PageHeaderProps) {
  const t = useTranslations("dashboard");
  return (
    <div className={cn("mb-6", className)}>
      {breadcrumbs && breadcrumbs.length > 0 && (
        <nav aria-label={t("breadcrumb")} className="mb-3">
          <ol className="text-muted-foreground flex flex-wrap items-center gap-1.5 text-xs">
            {breadcrumbs.map((c, i) => {
              const last = i === breadcrumbs.length - 1;
              return (
                <li key={`${c.label}-${i}`} className="flex items-center gap-1.5">
                  {c.href && !last ? (
                    <Link href={c.href} className="hover:text-foreground transition-colors">
                      {c.label}
                    </Link>
                  ) : (
                    <span
                      aria-current={last ? "page" : undefined}
                      className={cn(last && "text-foreground font-medium")}
                    >
                      {c.label}
                    </span>
                  )}
                  {!last && <ChevronRight className="h-3 w-3 opacity-50" />}
                </li>
              );
            })}
          </ol>
        </nav>
      )}

      {/* Keep actions beside the title when they fit, and wrap them otherwise.
          The introduction owns its row so a long toolbar cannot squeeze it.
          On phones it stays before the actions, in the document's reading order. */}
      <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
        <div className="min-w-0 flex-1 basis-80">
          <div className="flex min-h-9 items-center gap-3">
            <h1 className="text-foreground min-w-0 flex-1 text-xl leading-tight font-semibold tracking-tight text-balance md:text-2xl">
              {title}
            </h1>
            {/* On a phone the help sits with the title it explains, rather than
                alone on a row under the wrapped actions. */}
            <span className="md:hidden">
              <RestartTourButton />
            </span>
          </div>
          {/* Status belongs to the thing named, so it sits under the name - it
              used to float above the action buttons, reading as a caption for
              them rather than as a fact about the page. */}
          {badges && (
            <div
              role="group"
              aria-label={t("pageStatus")}
              className="mt-2 flex flex-wrap items-center gap-2 whitespace-nowrap"
            >
              {badges}
            </div>
          )}
        </div>
        {description && (
          <div className="order-1 basis-full md:order-2">
            <p className="text-muted-foreground line-clamp-2 max-w-2xl text-sm leading-relaxed text-pretty">
              {description}
            </p>
          </div>
        )}
        {/* Wrapped on a phone: scrolled sideways, the Builder's last actions
            sat past the screen's edge with nothing saying they were there. */}
        <div className="order-2 flex max-w-full min-w-0 flex-wrap items-center gap-2 md:order-1 md:justify-end">
          {actions}
          <span className="hidden md:inline-flex">
            <RestartTourButton />
          </span>
        </div>
      </div>
    </div>
  );
}
