import { ContextHelp } from "@/components/ui/context-help";
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
  /** Live summaries remain visible; explanatory introductions live in contextual help. */
  descriptionMode?: "help" | "summary";
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
  descriptionMode = "help",
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
                    <Link
                      href={c.href}
                      className="hover:text-foreground touch:min-h-11 focus-visible:outline-ring inline-flex items-center rounded-md transition-colors focus-visible:outline-2 focus-visible:outline-offset-2"
                    >
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
                  {!last && <ChevronRight className="h-3 w-3 shrink-0 opacity-50" aria-hidden />}
                </li>
              );
            })}
          </ol>
        </nav>
      )}

      {/* Keep the primary actions beside the title; wrap naturally on a narrow screen. */}
      <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-3">
        <div className="min-w-0 flex-1 basis-80">
          <div className="flex min-h-9 items-center gap-3">
            <h1 className="text-foreground min-w-0 text-xl leading-tight font-semibold tracking-tight text-balance md:text-2xl">
              {title}
            </h1>
            {description && descriptionMode === "help" && <ContextHelp>{description}</ContextHelp>}
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
        {description && descriptionMode === "summary" && (
          <p className="text-muted-foreground order-1 basis-full text-sm leading-relaxed md:order-2">
            {description}
          </p>
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
