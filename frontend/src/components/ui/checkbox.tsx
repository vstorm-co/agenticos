"use client";

import * as React from "react";
import * as CheckboxPrimitive from "@radix-ui/react-checkbox";
import { Check, Minus } from "lucide-react";
import { cn } from "@/lib/utils";

const Checkbox = React.forwardRef<
  React.ComponentRef<typeof CheckboxPrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof CheckboxPrimitive.Root>
>(({ className, ...props }, ref) => (
  <CheckboxPrimitive.Root
    ref={ref}
    className={cn(
      "peer group/checkbox focus-visible:ring-ring focus-visible:ring-offset-background touch:size-11 inline-flex size-4 shrink-0 touch-manipulation items-center justify-center rounded-md focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-50",
      className,
    )}
    {...props}
  >
    <span className="border-input group-data-[state=checked]/checkbox:border-primary group-data-[state=checked]/checkbox:bg-primary group-data-[state=checked]/checkbox:text-primary-foreground group-data-[state=indeterminate]/checkbox:border-primary group-data-[state=indeterminate]/checkbox:bg-primary group-data-[state=indeterminate]/checkbox:text-primary-foreground pointer-events-none flex size-4 shrink-0 items-center justify-center rounded-sm border-[1.5px] transition-colors duration-[var(--duration-fast)]">
      <CheckboxPrimitive.Indicator className="flex items-center justify-center text-current">
        <Check
          className="size-3.5 group-data-[state=indeterminate]/checkbox:hidden"
          aria-hidden="true"
        />
        <Minus
          className="hidden size-3.5 group-data-[state=indeterminate]/checkbox:block"
          aria-hidden="true"
        />
      </CheckboxPrimitive.Indicator>
    </span>
  </CheckboxPrimitive.Root>
));
Checkbox.displayName = CheckboxPrimitive.Root.displayName;

export { Checkbox };
