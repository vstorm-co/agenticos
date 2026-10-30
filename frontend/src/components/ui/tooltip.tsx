"use client";

import * as React from "react";
import * as TooltipPrimitive from "@radix-ui/react-tooltip";
import { cn } from "@/lib/utils";

const TooltipProvider = TooltipPrimitive.Provider;
const Tooltip = TooltipPrimitive.Root;
const TooltipTrigger = TooltipPrimitive.Trigger;

const TooltipContent = React.forwardRef<
  React.ComponentRef<typeof TooltipPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof TooltipPrimitive.Content>
>(({ className, sideOffset = 4, ...props }, ref) => (
  <TooltipPrimitive.Portal>
    <TooltipPrimitive.Content
      ref={ref}
      sideOffset={sideOffset}
      className={cn(
        // Deliberately NOT the accent. A tooltip is a neutral inverse surface:
        // it labels whatever it points at, so tinting it would imply the
        // labelled thing is the primary action.
        "bg-foreground text-background data-[state=delayed-open]:animate-in data-[state=instant-open]:animate-in data-[state=closed]:animate-out fade-in-0 fade-out-0 zoom-in-95 zoom-out-95 z-50 max-w-[min(20rem,calc(100vw-1.5rem))] origin-[var(--radix-tooltip-content-transform-origin)] rounded-lg px-3 py-2 text-xs leading-relaxed break-words",
        className,
      )}
      {...props}
    />
  </TooltipPrimitive.Portal>
));
TooltipContent.displayName = TooltipPrimitive.Content.displayName;

export { Tooltip, TooltipTrigger, TooltipContent, TooltipProvider };
