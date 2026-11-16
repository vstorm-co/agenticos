"use client";

import * as React from "react";
import * as SwitchPrimitives from "@radix-ui/react-switch";
import { CONTROL_DISABLED, CONTROL_FOCUS, CONTROL_INVALID } from "./control-styles";
import { cn } from "@/lib/utils";

const Switch = React.forwardRef<
  React.ComponentRef<typeof SwitchPrimitives.Root>,
  React.ComponentPropsWithoutRef<typeof SwitchPrimitives.Root>
>(({ className, ...props }, ref) => (
  <SwitchPrimitives.Root
    className={cn(
      `${CONTROL_FOCUS} ${CONTROL_DISABLED} ${CONTROL_INVALID} peer group/switch touch:h-11 touch:w-11 inline-flex h-5 w-9 shrink-0 cursor-pointer items-center justify-center rounded-full`,
      className,
    )}
    {...props}
    ref={ref}
  >
    <span className="bg-field border-foreground/55 group-aria-checked/switch:border-primary group-aria-checked/switch:bg-primary group-aria-invalid/switch:border-destructive group-[:enabled:hover]/switch:border-foreground/60 pointer-events-none inline-flex h-5 w-9 shrink-0 items-center rounded-full border-2 transition-colors duration-[var(--duration-fast)]">
      <SwitchPrimitives.Thumb className="data-[state=checked]:bg-primary-foreground bg-muted-foreground block h-4 w-4 rounded-full shadow-sm ring-0 transition-transform duration-[var(--duration-fast)] data-[state=checked]:translate-x-4 data-[state=unchecked]:translate-x-0" />
    </span>
  </SwitchPrimitives.Root>
));
Switch.displayName = SwitchPrimitives.Root.displayName;

export { Switch };
