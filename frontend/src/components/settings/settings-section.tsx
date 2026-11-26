"use client";

import { useId, useState } from "react";
import { ChevronDown } from "lucide-react";
import { useChanged } from "@/hooks/use-changed";
import { DisclosureContent } from "@/components/ui/disclosure-content";
import { DISCLOSURE_TRIGGER } from "@/components/ui/control-styles";
import { ContextHelp } from "@/components/ui/context-help";
import type { ReactNode } from "react";
import type { LucideIcon } from "lucide-react";

import { cn } from "@/lib/utils";

interface SectionCardProps {
  title: string;
  description?: ReactNode;
  action?: ReactNode;
  children?: ReactNode;
  icon?: LucideIcon;
  danger?: boolean;
  tour?: string;
  className?: string;
  contentClassName?: string;
}

export function SectionCard({
  title,
  description,
  action,
  children,
  icon: Icon,
  danger = false,
  tour,
  className,
  contentClassName,
}: SectionCardProps) {
  return (
    <section
      className={cn(
        "min-w-0",
        danger
          ? "bg-card border-destructive/20 overflow-hidden rounded-xl border"
          : "border-border border-b",
        className,
      )}
    >
      <header
        data-tour={tour}
        className={cn(
          "flex flex-wrap items-center justify-between gap-3 py-4",
          danger && "border-border border-b px-5 sm:px-6",
        )}
      >
        <div className="flex min-w-0 flex-1 items-center gap-2.5">
          {Icon && (
            <span
              className={cn(
                "grid shrink-0 place-items-center",
                danger
                  ? "bg-destructive/10 text-destructive-ink size-9 rounded-xl"
                  : "text-muted-foreground size-5",
              )}
            >
              <Icon className="size-[18px]" strokeWidth={1.75} aria-hidden />
            </span>
          )}
          <div className="min-w-0">
            <div className="flex items-center gap-1">
              <h2 className="console-section-title text-foreground">{title}</h2>
              {description && !danger && <ContextHelp>{description}</ContextHelp>}
            </div>
            {description && danger && (
              <p className="text-muted-foreground max-w-2xl text-xs leading-5">{description}</p>
            )}
          </div>
        </div>
        {action && <div className="shrink-0">{action}</div>}
      </header>
      {children && (
        <div className={cn("py-5", danger && "px-5 sm:px-6", contentClassName)}>{children}</div>
      )}
    </section>
  );
}

interface SettingsSectionProps {
  tour?: string;
  toggleTour?: string;
  collapsible?: boolean;
  defaultOpen?: boolean;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
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
  tour,
  toggleTour,
  collapsible = false,
  defaultOpen = false,
  open: controlledOpen,
  onOpenChange,
  title,
  status,
  description,
  action,
  danger,
  children,
  className,
}: SettingsSectionProps) {
  const panelId = useId();
  const [internalOpen, setInternalOpen] = useState(defaultOpen);
  if (useChanged(defaultOpen) && defaultOpen) setInternalOpen(true);
  const open = controlledOpen ?? internalOpen;
  const setOpen = (next: boolean) => {
    setInternalOpen(next);
    onOpenChange?.(next);
  };
  return (
    <section
      data-tour={tour}
      className={cn(
        "min-w-0",
        danger
          ? "border-destructive/30 bg-destructive/[0.03] rounded-xl border p-4 sm:p-5"
          : "border-border border-b py-5",
        className,
      )}
    >
      <header
        className={cn(
          "flex flex-wrap items-center justify-between gap-3",
          children && (!collapsible || open) ? "mb-4" : "",
        )}
      >
        <div className="min-w-0 flex-1">
          <div className="flex items-center gap-1">
            <h2
              className={cn(
                "console-section-title",
                danger ? "text-destructive" : "text-foreground",
              )}
            >
              {collapsible ? (
                <button
                  id={`${panelId}-toggle`}
                  type="button"
                  data-tour={toggleTour}
                  aria-expanded={open}
                  aria-controls={panelId}
                  onClick={() => setOpen(!open)}
                  data-press-feedback="quiet"
                  className={DISCLOSURE_TRIGGER}
                >
                  <ChevronDown
                    aria-hidden
                    className={cn(
                      "size-4 shrink-0 transition-transform motion-reduce:transition-none",
                      !open && "-rotate-90",
                    )}
                  />
                  {title}
                </button>
              ) : (
                title
              )}
            </h2>
            {description && !danger && !collapsible && <ContextHelp>{description}</ContextHelp>}
            {status}
          </div>
          {description && (danger || collapsible) && (
            <p className="text-muted-foreground mt-1 max-w-3xl text-sm leading-relaxed">
              {description}
            </p>
          )}
        </div>
        {action && <div className="shrink-0">{action}</div>}
      </header>
      {collapsible ? (
        <DisclosureContent
          id={panelId}
          open={open}
          triggerId={`${panelId}-toggle`}
          mountOnOpen={false}
          onReveal={() => setOpen(true)}
        >
          {children}
        </DisclosureContent>
      ) : (
        <div>{children}</div>
      )}
    </section>
  );
}
