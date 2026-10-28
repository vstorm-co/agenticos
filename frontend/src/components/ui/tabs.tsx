"use client";

import * as React from "react";
import * as TabsPrimitive from "@radix-ui/react-tabs";
import { cn } from "@/lib/utils";

import { SCROLL_FADE, useScrollFade } from "./scroll-fade";

const Tabs = TabsPrimitive.Root;

const TabsList = React.forwardRef<
  React.ComponentRef<typeof TabsPrimitive.List>,
  React.ComponentPropsWithoutRef<typeof TabsPrimitive.List>
>(({ className, ...props }, ref) => {
  const strip = React.useRef<HTMLDivElement | null>(null);
  useScrollFade(strip);
  return (
    <TabsPrimitive.List
      ref={(node) => {
        strip.current = node;
        if (typeof ref === "function") ref(node);
        else if (ref) ref.current = node;
      }}
      className={cn(
        // The underline strip is the console's one tab dialect - the rag page's
        // look, promoted to the primitive so every tab strip reads the same.
        // A strip wider than a phone scrolls itself rather than widening the
        // page: it pushed the main column sideways, and focusing a tab scrolled
        // the whole page out from under the reader.
        // The strip's line is an inset shadow, not a border: a scroll container
        // clips to inside its border, so a border here cut the active tab's
        // 2px underline to a hairline nobody could tell from the line itself.
        "text-muted-foreground flex max-w-full scrollbar-none gap-6 overflow-x-auto overflow-y-hidden bg-transparent shadow-[inset_0_-1px_0_var(--color-border)] [&>*]:shrink-0",
        SCROLL_FADE,
        className,
      )}
      {...props}
    />
  );
});
TabsList.displayName = TabsPrimitive.List.displayName;

const TabsTrigger = React.forwardRef<
  React.ComponentRef<typeof TabsPrimitive.Trigger>,
  React.ComponentPropsWithoutRef<typeof TabsPrimitive.Trigger>
>(({ className, ...props }, ref) => (
  <TabsPrimitive.Trigger
    ref={ref}
    className={cn(
      // The active tab is the one carrying the ink: a bottom border in the
      // foreground colour, the label darkening with it - no pill, no fill.
      "focus-visible:ring-ring inline-flex items-center gap-2 border-b-2 border-transparent px-1 pb-3 text-sm font-medium whitespace-nowrap transition-colors focus-visible:ring-2 focus-visible:outline-none focus-visible:ring-inset disabled:pointer-events-none disabled:opacity-50",
      "hover:text-foreground data-[state=active]:border-foreground data-[state=active]:text-foreground",
      className,
    )}
    {...props}
  />
));
TabsTrigger.displayName = TabsPrimitive.Trigger.displayName;

const TabsContent = React.forwardRef<
  React.ComponentRef<typeof TabsPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof TabsPrimitive.Content>
>(({ className, ...props }, ref) => (
  <TabsPrimitive.Content
    ref={ref}
    className={cn(
      "focus-visible:ring-ring mt-2 focus-visible:ring-2 focus-visible:outline-none focus-visible:ring-inset data-[state=inactive]:hidden",
      className,
    )}
    {...props}
  />
));
TabsContent.displayName = TabsPrimitive.Content.displayName;

export { Tabs, TabsList, TabsTrigger, TabsContent };
