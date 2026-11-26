"use client";

import { forwardRef, useState, type HTMLAttributes, type ReactNode } from "react";
import { ChevronRight } from "lucide-react";

import { NativeDisclosure } from "@/components/ui/native-disclosure";
import { useChanged } from "@/hooks/use-changed";
import { cn } from "@/lib/utils";

/** Native sections retain mounted editors and can be opened by deep-link highlighting. */
export const BuildSection = forwardRef<
  HTMLDivElement,
  HTMLAttributes<HTMLDivElement> & {
    title: string;
    /** An inset row in one settings panel instead of a separate card. */
    framed?: boolean;
    /** Primary settings can stay visible without a redundant disclosure. */
    collapsible?: boolean;
    headerEnd?: ReactNode;
    description?: ReactNode;
    /** Current configuration, readable before opening the editor. */
    summary?: ReactNode;
    defaultOpen?: boolean;
    open?: boolean;
    onOpenChange?: (open: boolean) => void;
  }
>(function BuildSection(
  {
    title,
    framed = true,
    collapsible = true,
    headerEnd,
    description,
    summary,
    defaultOpen = false,
    open: controlled,
    onOpenChange,
    className,
    children,
    ...props
  },
  ref,
) {
  const [ownOpen, setOwnOpen] = useState(defaultOpen);
  if (useChanged(defaultOpen) && defaultOpen) setOwnOpen(true);
  const open = controlled ?? ownOpen;
  const frame = cn(
    "has-[>details>summary:focus-visible]:outline-ring min-w-0 has-[>details>summary:focus-visible]:outline-2 has-[>details>summary:focus-visible]:outline-offset-2",
    framed ? "bg-card rounded-xl border" : "bg-transparent",
    className,
  );
  const heading = (
    <span
      className={cn(
        "min-w-0 flex-1",
        !framed && "flex items-baseline gap-x-3",
        !framed && !collapsible && "flex-wrap gap-y-0.5",
      )}
    >
      <span className="block shrink-0 text-sm font-medium">{title}</span>
      {summary && (
        <span
          title={typeof summary === "string" ? summary : undefined}
          className={cn(
            "text-muted-foreground block font-normal",
            framed ? "mt-0.5 text-sm leading-relaxed" : "text-[13px] leading-5",
            !framed && collapsible && "truncate",
          )}
        >
          {summary}
        </span>
      )}
    </span>
  );
  const content = (
    <div className="min-w-0 space-y-4 px-4 pb-4 sm:px-5 sm:pb-5">
      {description && <p className="text-muted-foreground text-[13px] leading-5">{description}</p>}
      {children}
    </div>
  );
  if (!collapsible)
    return (
      <div ref={ref} data-slot="build-section" className={frame} {...props}>
        <header className="flex items-center gap-3 px-4 py-3 sm:px-5">
          <h2 aria-label={title} className="min-w-0 flex-1">
            {heading}
          </h2>
          {headerEnd}
        </header>
        {content}
      </div>
    );
  return (
    <div ref={ref} data-slot="build-section" className={frame} {...props}>
      <NativeDisclosure
        className="group/build"
        data-focus-frame
        open={open}
        onToggle={(event) => {
          setOwnOpen(event.currentTarget.open);
          onOpenChange?.(event.currentTarget.open);
        }}
      >
        <summary
          aria-label={title}
          className="hover:text-muted-foreground flex min-h-12 cursor-pointer list-none items-center gap-3 rounded-xl px-4 py-3 transition-colors outline-none motion-reduce:transition-none sm:px-5 [&::-webkit-details-marker]:hidden"
        >
          {heading}
          {headerEnd}
          <ChevronRight
            className="text-muted-foreground size-4 shrink-0 transition-transform group-open/build:rotate-90 motion-reduce:transition-none"
            aria-hidden
          />
        </summary>
        {content}
      </NativeDisclosure>
    </div>
  );
});
