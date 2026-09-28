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
    <div className={cn("mb-6 md:mb-8", className)}>
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

      {/* Wrapping rather than squeezing. With the actions fixed and the text
          column shrinking to fit beside them, a page with five buttons broke
          its own title over two lines and every pill in it over two more. The
          text column claims 20rem before anything else, and when that and the
          actions do not fit on one line the actions move under the title - the
          description's length plays no part, since the basis, not the text,
          decides the line. The actions sit level with the title rather than
          with the description's last line: a four-line description used to
          leave the page's primary button floating halfway down the header. */}
      <div className="flex flex-wrap items-start justify-between gap-x-6 gap-y-4">
        <div className="min-w-0 flex-1 basis-80">
          <h1 className="text-foreground text-2xl leading-tight font-semibold tracking-tight text-balance">
            {title}
          </h1>
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
          {description && (
            <p className="text-muted-foreground mt-1.5 max-w-2xl text-sm leading-relaxed text-pretty">
              {description}
            </p>
          )}
        </div>
        <div className="flex max-w-full min-w-0 flex-wrap items-center gap-2 sm:justify-end">
          {actions}
          <RestartTourButton />
        </div>
      </div>
    </div>
  );
}
