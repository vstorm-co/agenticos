"use client";

import { useId, useState, type ReactNode } from "react";
import { ChevronDown, type LucideIcon } from "lucide-react";
import { DisclosureContent } from "@/components/ui/disclosure-content";
import { useChanged } from "@/hooks/use-changed";
import { cn } from "@/lib/utils";

interface ServiceCardProps {
  title: string;
  description: string;
  icon: LucideIcon;
  action: ReactNode;
  status?: ReactNode;
  children?: ReactNode;
  collapsible?: boolean;
  defaultOpen?: boolean;
  open?: boolean;
  onOpenChange?: (open: boolean) => void;
  id?: string;
  testId?: string;
  toggleTour?: string;
}

/** The shared appearance and disclosure for each organization AI service. */
export function ServiceCard({
  title,
  description,
  icon: Icon,
  action,
  status,
  children,
  collapsible = false,
  defaultOpen = false,
  open: controlledOpen,
  onOpenChange,
  id,
  testId,
  toggleTour,
}: ServiceCardProps) {
  const generatedId = useId();
  const panelId = id ?? generatedId;
  const [internalOpen, setInternalOpen] = useState(defaultOpen);
  if (useChanged(defaultOpen) && defaultOpen) setInternalOpen(true);
  const open = controlledOpen ?? internalOpen;
  const expandable = collapsible && Boolean(children);
  const changeOpen = (next: boolean) => {
    setInternalOpen(next);
    onOpenChange?.(next);
  };
  return (
    <section
      aria-label={title}
      data-slot="service-card"
      data-testid={testId}
      className="bg-card min-w-0 overflow-hidden rounded-xl border"
    >
      <header className="has-[[data-slot=service-trigger]:hover]:bg-control-hover relative isolate flex items-start gap-3 p-4 transition-colors sm:p-5">
        <span
          data-slot="service-icon"
          className="bg-muted text-foreground/80 grid size-9 shrink-0 place-items-center rounded-lg"
        >
          <Icon className="size-[18px]" strokeWidth={1.75} aria-hidden />
        </span>
        <div className="flex min-w-0 flex-1 items-start gap-1.5">
          <h2 aria-label={title} className="min-w-0 flex-1 text-sm font-semibold">
            {expandable ? (
              <button
                id={`${panelId}-toggle`}
                data-tour={toggleTour}
                data-slot="service-trigger"
                type="button"
                aria-label={title}
                aria-describedby={`${panelId}-description`}
                aria-expanded={open}
                aria-controls={panelId}
                onClick={() => changeOpen(!open)}
                // The native button's hit area and focus boundary cover the header;
                // independent status/actions remain above it as sibling controls.
                className="focus-visible:after:outline-ring flex min-h-9 w-full items-start gap-2 text-left outline-none select-none after:absolute after:inset-0 after:cursor-pointer focus-visible:after:outline-2 focus-visible:after:-outline-offset-2"
              >
                <ChevronDown
                  aria-hidden
                  className={cn(
                    "mt-0.5 size-4 shrink-0 transition-transform",
                    !open && "-rotate-90",
                  )}
                />
                <span className="min-w-0">
                  <span className="block">{title}</span>
                  <span
                    id={`${panelId}-description`}
                    className="text-muted-foreground mt-1 block text-xs leading-5 font-normal"
                  >
                    {description}
                  </span>
                </span>
              </button>
            ) : (
              <span className="block min-h-9">
                <span className="block">{title}</span>
                <span className="text-muted-foreground mt-1 block text-xs leading-5 font-normal">
                  {description}
                </span>
              </span>
            )}
          </h2>
          {status && <div className="relative z-10 empty:hidden">{status}</div>}
        </div>
        <div className="relative z-10 shrink-0">{action}</div>
      </header>
      {children && (
        <DisclosureContent
          id={panelId}
          open={!expandable || open}
          triggerId={expandable ? `${panelId}-toggle` : undefined}
          mountOnOpen={false}
          onReveal={() => changeOpen(true)}
        >
          <div className="space-y-4 border-t px-4 py-4 sm:px-5">{children}</div>
        </DisclosureContent>
      )}
    </section>
  );
}
