"use client";

import * as React from "react";
import * as SwitchPrimitives from "@radix-ui/react-switch";
import { cn } from "@/lib/utils";

const Switch = React.forwardRef<
  React.ComponentRef<typeof SwitchPrimitives.Root>,
  React.ComponentPropsWithoutRef<typeof SwitchPrimitives.Root>
>(({ className, ...props }, ref) => (
  <SwitchPrimitives.Root
    className={cn(
      "peer group/switch focus-visible:ring-ring focus-visible:ring-offset-background touch:h-11 touch:w-11 inline-flex h-5 w-9 shrink-0 cursor-pointer items-center justify-center rounded-full focus-visible:ring-2 focus-visible:ring-offset-2 focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-50",
      className,
    )}
    {...props}
    ref={ref}
  >
    <span className="group-data-[state=checked]/switch:bg-success group-data-[state=unchecked]/switch:bg-input pointer-events-none inline-flex h-5 w-9 shrink-0 items-center rounded-full border-2 border-transparent shadow-sm transition-colors">
      <SwitchPrimitives.Thumb className="bg-background block h-4 w-4 rounded-full shadow-lg ring-0 transition-transform data-[state=checked]:translate-x-4 data-[state=unchecked]:translate-x-0" />
    </span>
  </SwitchPrimitives.Root>
));
Switch.displayName = SwitchPrimitives.Root.displayName;

export { Switch };
