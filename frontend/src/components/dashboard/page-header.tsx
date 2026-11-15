"use client";

import Link from "next/link";
import { ChevronRight, MoreHorizontal, X } from "lucide-react";
import { useEffect, useId, useRef, useState, type ReactNode } from "react";
import { Button } from "@/components/ui/button";

import { PageHelp } from "@/components/onboarding/page-help";
import { cn } from "@/lib/utils";
import { useTranslations } from "next-intl";

export interface Crumb {
  label: string;
  href?: string;
}

interface PageHeaderProps {
  title: ReactNode;
  /** A resource mark or picker beside the heading, outside its accessible name. */
  icon?: ReactNode;
  description?: ReactNode;
  /** Live summaries remain visible; explanatory introductions live in contextual help. */
  descriptionMode?: "help" | "summary";
  /** Breadcrumb trail (last item is the current page; omit href on it). */
  breadcrumbs?: Crumb[];
  /** Right-aligned actions (buttons, etc.). */
  actions?: ReactNode;
  /** Secondary commands stay inline on desktop and fold behind one control on phones. */
  secondaryActions?: ReactNode;
  /** State of the thing on the page (status pills), set above the actions. */
  badges?: ReactNode;
  className?: string;
}

/**
 * The single page-header used across the whole dashboard. Keeps title/description/
 * actions/breadcrumbs consistent and theme-aware. The parent owns outer spacing.
 */
export function PageHeader({
  title,
  icon,
  description,
  descriptionMode = "help",
  breadcrumbs,
  actions,
  secondaryActions,
  badges,
  className,
}: PageHeaderProps) {
  const t = useTranslations("dashboard");
  const [secondaryOpen, setSecondaryOpen] = useState(false);
  const secondaryId = useId();
  const header = useRef<HTMLDivElement>(null);
  const secondaryButton = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    if (!secondaryOpen) return;
    const outside = (event: PointerEvent) => {
      if (event.target instanceof Node && !header.current?.contains(event.target))
        setSecondaryOpen(false);
    };
    const escape = (event: KeyboardEvent) => {
      if (event.key === "Escape" && !event.defaultPrevented) {
        setSecondaryOpen(false);
        secondaryButton.current?.focus();
      }
    };
    window.addEventListener("pointerdown", outside);
    window.addEventListener("keydown", escape);
    return () => {
      window.removeEventListener("pointerdown", outside);
      window.removeEventListener("keydown", escape);
    };
  }, [secondaryOpen]);
  return (
    <div ref={header} className={cn("shrink-0", className)}>
      {breadcrumbs && breadcrumbs.length > 0 && (
        <nav aria-label={t("breadcrumb")} className="mb-1 sm:mb-3">
          <ol className="text-muted-foreground flex flex-wrap items-center gap-1.5 text-xs">
            {breadcrumbs.map((c, i) => {
              const last = i === breadcrumbs.length - 1;
              return (
                <li key={`${c.label}-${i}`} className="flex items-center gap-1.5">
                  {c.href && !last ? (
                    <Link
                      href={c.href}
                      className="hover:text-foreground touch:min-h-8 focus-visible:outline-ring inline-flex items-center rounded-md transition-colors focus-visible:outline-2 focus-visible:outline-offset-2"
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
      <div className="flex flex-wrap items-start justify-between gap-x-3 gap-y-2 sm:gap-x-6 sm:gap-y-3">
        <div className="min-w-0 flex-1 basis-auto">
          <div className="flex min-h-9 items-center gap-2 sm:gap-3">
            {icon}
            <h1 className="text-foreground min-w-0 text-lg leading-tight font-semibold tracking-tight text-balance sm:text-xl md:text-2xl">
              {title}
            </h1>
            <PageHelp description={descriptionMode === "help" ? description : undefined} />
          </div>
          {/* Status belongs to the thing named, so it sits under the name - it
              used to float above the action buttons, reading as a caption for
              them rather than as a fact about the page. */}
          {badges && (
            <div
              role="group"
              aria-label={t("pageStatus")}
              className="mt-1 flex flex-wrap items-center gap-2 whitespace-nowrap sm:mt-2"
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
        <div
          className={cn(
            "page-actions order-2 flex w-auto max-w-full min-w-0 flex-wrap items-center gap-2 md:order-1 md:justify-end",
            secondaryOpen && "max-md:w-full",
          )}
        >
          {secondaryActions && (
            <>
              <Button
                ref={secondaryButton}
                type="button"
                variant="outline"
                size="icon"
                className="md:hidden"
                aria-label={t("morePageActions")}
                aria-expanded={secondaryOpen}
                data-state={secondaryOpen ? "active" : "inactive"}
                aria-controls={secondaryId}
                data-tour="page-secondary-actions"
                onClick={() => setSecondaryOpen(!secondaryOpen)}
              >
                {secondaryOpen ? <X aria-hidden /> : <MoreHorizontal aria-hidden />}
              </Button>
              <div
                id={secondaryId}
                data-secondary-actions
                className={cn(
                  "order-2 grid basis-full grid-cols-2 gap-2 md:contents max-md:[&>div]:col-span-2",
                  !secondaryOpen && "max-md:hidden",
                )}
              >
                {secondaryActions}
              </div>
            </>
          )}
          {actions}
        </div>
      </div>
    </div>
  );
}
