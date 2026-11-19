"use client";

import { forwardRef, useId, useState, type HTMLAttributes, type ReactNode } from "react";
import { ChevronRight } from "lucide-react";

import { NativeDisclosure } from "@/components/ui/native-disclosure";
import { useChanged } from "@/hooks/use-changed";
import { cn } from "@/lib/utils";

/** Native sections retain mounted editors and can be opened by deep-link highlighting. */
export const BuildSection = forwardRef<
  HTMLDivElement,
  HTMLAttributes<HTMLDivElement> & {
    title: string;
    description?: ReactNode;
    defaultOpen?: boolean;
    open?: boolean;
    onOpenChange?: (open: boolean) => void;
  }
>(function BuildSection(
  {
    title,
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
  const descriptionId = useId();
  const [ownOpen, setOwnOpen] = useState(defaultOpen);
  if (useChanged(defaultOpen) && defaultOpen) setOwnOpen(true);
  const open = controlled ?? ownOpen;
  return (
    <div
      ref={ref}
      data-slot="build-section"
      className={cn("min-w-0 border-b last:border-b-0", className)}
      {...props}
    >
      <NativeDisclosure
        className="group/build"
        open={open}
        onToggle={(event) => {
          setOwnOpen(event.currentTarget.open);
          onOpenChange?.(event.currentTarget.open);
        }}
      >
        <summary
          aria-label={title}
          aria-describedby={description ? descriptionId : undefined}
          className="focus-visible:outline-foreground/60 flex min-h-16 cursor-pointer list-none items-start gap-3 rounded-lg p-5 focus-visible:outline-2 focus-visible:outline-offset-[-2px] [&::-webkit-details-marker]:hidden"
        >
          <ChevronRight
            className="text-muted-foreground mt-0.5 size-4 shrink-0 transition-transform group-open/build:rotate-90 motion-reduce:transition-none"
            aria-hidden
          />
          <span className="min-w-0 flex-1 space-y-1">
            <span className="block text-sm font-semibold">{title}</span>
            {description && (
              <span
                id={descriptionId}
                className="text-muted-foreground block text-[13px] leading-5"
              >
                {description}
              </span>
            )}
          </span>
        </summary>
        <div className="min-w-0 space-y-5 px-5 pb-5">{children}</div>
      </NativeDisclosure>
    </div>
  );
});
