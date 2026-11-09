import { ContextHelp } from "@/components/ui/context-help";
import type { ReactNode } from "react";
import type { LucideIcon } from "lucide-react";

import { cn } from "@/lib/utils";

interface SectionCardProps {
  title: string;
  description?: string;
  action?: ReactNode;
  children?: ReactNode;
  icon?: LucideIcon;
  danger?: boolean;
  tour?: string;
}

export function SectionCard({
  title,
  description,
  action,
  children,
  icon: Icon,
  danger = false,
  tour,
}: SectionCardProps) {
  return (
    <section
      className={cn(
        "bg-card shadow-card overflow-hidden rounded-2xl border",
        danger ? "border-destructive/20" : "border-foreground/[0.07]",
      )}
    >
      <header
        data-tour={tour}
        className="border-foreground/[0.06] flex flex-wrap items-center justify-between gap-3 border-b px-5 py-4 sm:px-6"
      >
        <div className="flex min-w-0 flex-1 items-start gap-3">
          {Icon && (
            <span
              className={cn(
                "grid size-9 shrink-0 place-items-center rounded-xl",
                danger
                  ? "bg-destructive/10 text-destructive-ink"
                  : "bg-foreground/5 text-foreground/80",
              )}
            >
              <Icon className="size-[18px]" strokeWidth={1.75} aria-hidden />
            </span>
          )}
          <div className="min-w-0 space-y-1">
            <h2 className="text-foreground text-sm font-semibold">{title}</h2>
            {description && (
              <p className="text-muted-foreground max-w-2xl text-xs leading-5">{description}</p>
            )}
          </div>
        </div>
        {action && <div className="shrink-0">{action}</div>}
      </header>
      {children && <div className="p-5 sm:p-6">{children}</div>}
    </section>
  );
}

interface SettingsSectionProps {
  title: string;
  status?: ReactNode;
  description?: string;
  /** Right-aligned action (e.g. "Save changes" button). */
  action?: ReactNode;
  /** Subdued danger styling for destructive sections. */
  danger?: boolean;
  children: ReactNode;
  className?: string;
}

export function SettingsSection({
  title,
  status,
  description,
  action,
  danger,
  children,
  className,
}: SettingsSectionProps) {
  return (
    <section
      className={cn(
        "bg-card rounded-2xl border p-4 sm:p-5",
        danger ? "border-destructive/30 bg-destructive/[0.03]" : "border-foreground/10",
        className,
      )}
    >
      <header
        className={cn("flex flex-wrap items-start justify-between gap-3", children ? "mb-4" : "")}
      >
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1">
            <h2
              className={cn(
                "text-base font-semibold tracking-tight",
                danger ? "text-destructive" : "text-foreground",
              )}
            >
              {title}
            </h2>
            {description && !danger && <ContextHelp>{description}</ContextHelp>}
            {status}
          </div>
          {description && danger && (
            <p className="text-muted-foreground mt-1 text-sm leading-relaxed">{description}</p>
          )}
        </div>
        {action && <div className="shrink-0">{action}</div>}
      </header>
      {children}
    </section>
  );
}
