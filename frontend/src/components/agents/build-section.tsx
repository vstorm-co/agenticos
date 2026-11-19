"use client";

import { forwardRef, useState, type HTMLAttributes, type ReactNode } from "react";
import { ChevronRight, SlidersHorizontal, type LucideIcon } from "lucide-react";

import { NativeDisclosure } from "@/components/ui/native-disclosure";
import { useChanged } from "@/hooks/use-changed";
import { cn } from "@/lib/utils";

/** Native sections retain mounted editors and can be opened by deep-link highlighting. */
export const BuildSection = forwardRef<
  HTMLDivElement,
  HTMLAttributes<HTMLDivElement> & {
    title: string;
    icon?: LucideIcon;
    headerEnd?: ReactNode;
    description?: ReactNode;
    defaultOpen?: boolean;
    open?: boolean;
    onOpenChange?: (open: boolean) => void;
  }
>(function BuildSection(
  {
    title,
    icon: Icon = SlidersHorizontal,
    headerEnd,
    description,
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
  return (
    <div
      ref={ref}
      data-slot="build-section"
      className={cn(
        "bg-card has-[>details>summary:focus-visible]:outline-ring min-w-0 rounded-xl border has-[>details>summary:focus-visible]:outline-2 has-[>details>summary:focus-visible]:outline-offset-2",
        className,
      )}
      {...props}
    >
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
          className="hover:text-muted-foreground flex min-h-16 cursor-pointer list-none items-center gap-3 rounded-xl p-4 transition-colors outline-none motion-reduce:transition-none sm:p-5 [&::-webkit-details-marker]:hidden"
        >
          <span className="bg-muted text-foreground/80 grid size-9 shrink-0 place-items-center rounded-lg">
            <Icon className="size-[18px]" strokeWidth={1.75} aria-hidden />
          </span>
          <span className="min-w-0 flex-1 text-sm font-semibold">{title}</span>
          {headerEnd}
          <ChevronRight
            className="text-muted-foreground size-4 shrink-0 transition-transform group-open/build:rotate-90 motion-reduce:transition-none"
            aria-hidden
          />
        </summary>
        <div className="min-w-0 space-y-4 px-4 pb-4 sm:px-5 sm:pb-5">
          {description && (
            <p className="text-muted-foreground text-[13px] leading-5">{description}</p>
          )}
          {children}
        </div>
      </NativeDisclosure>
    </div>
  );
});
