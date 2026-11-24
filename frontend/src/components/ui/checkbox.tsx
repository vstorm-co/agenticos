"use client";

import * as React from "react";
import * as CheckboxPrimitive from "@radix-ui/react-checkbox";
import { Check, Minus } from "lucide-react";
import { CONTROL_DISABLED, CONTROL_FOCUS, CONTROL_INVALID } from "./control-styles";
import { cn } from "@/lib/utils";

const Checkbox = React.forwardRef<
  React.ComponentRef<typeof CheckboxPrimitive.Root>,
  React.ComponentPropsWithoutRef<typeof CheckboxPrimitive.Root>
>(({ className, ...props }, ref) => (
  <CheckboxPrimitive.Root
    ref={ref}
    className={cn(
      `${CONTROL_FOCUS} ${CONTROL_DISABLED} ${CONTROL_INVALID} peer group/checkbox touch:size-11 inline-flex size-4 shrink-0 touch-manipulation items-center justify-center rounded-md`,
      className,
    )}
    {...props}
  >
    <span className="border-foreground/55 bg-field group-data-[state=checked]/checkbox:border-primary group-data-[state=checked]/checkbox:bg-primary group-data-[state=checked]/checkbox:text-primary-foreground group-data-[state=indeterminate]/checkbox:border-primary group-data-[state=indeterminate]/checkbox:bg-primary group-data-[state=indeterminate]/checkbox:text-primary-foreground group-aria-invalid/checkbox:border-destructive group-[:enabled:hover]/checkbox:border-foreground/60 pointer-events-none flex size-4 shrink-0 items-center justify-center rounded-sm border-[1.5px] transition-colors duration-[var(--duration-fast)]">
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
