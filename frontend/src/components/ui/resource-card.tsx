"use client";

import { forwardRef, type HTMLAttributes } from "react";

import { Card } from "./card";
import { cn } from "@/lib/utils";

/** Resource galleries share one frame; their domain owns links, state and actions. */
export const ResourceCard = forwardRef<HTMLDivElement, HTMLAttributes<HTMLDivElement>>(
  ({ className, ...props }, ref) => (
    <Card
      ref={ref}
      data-slot="resource-card"
      className={cn(
        "hover:border-foreground/25 relative flex h-full min-h-64 flex-col rounded-2xl p-5 transition-colors",
        className,
      )}
      {...props}
    />
  ),
);
ResourceCard.displayName = "ResourceCard";

export function ResourceCardHeader({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("relative flex items-start gap-3", className)} {...props} />;
}

export function ResourceCardDescription({
  className,
  ...props
}: HTMLAttributes<HTMLParagraphElement>) {
  return (
    <p
      className={cn(
        "text-muted-foreground relative my-5 line-clamp-3 flex-1 text-sm leading-relaxed break-words",
        className,
      )}
      {...props}
    />
  );
}

export function ResourceCardFooter({ className, ...props }: HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn("relative mt-auto flex flex-wrap items-center gap-2 border-t pt-4", className)}
      {...props}
    />
  );
}
