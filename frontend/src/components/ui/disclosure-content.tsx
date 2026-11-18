"use client";

import { useLayoutEffect, useRef, useState, type ComponentPropsWithoutRef } from "react";

import { cn } from "@/lib/utils";

interface DisclosureContentProps extends ComponentPropsWithoutRef<"div"> {
  open: boolean;
  triggerId?: string;
  /** Forms may need to register values before their section is first opened. */
  mountOnOpen?: boolean;
}

/** Keep visited content stable while an interruptible disclosure opens or closes. */
export function DisclosureContent({
  open,
  triggerId,
  mountOnOpen = true,
  children,
  className,
  ...props
}: DisclosureContentProps) {
  const [visited, setVisited] = useState(open || !mountOnOpen);
  const ref = useRef<HTMLDivElement>(null);
  if (open && !visited) setVisited(true);
  useLayoutEffect(() => {
    if (!open && ref.current?.contains(document.activeElement)) {
      const trigger = triggerId ? document.getElementById(triggerId) : null;
      if (trigger) trigger.focus();
      else if (document.activeElement instanceof HTMLElement) document.activeElement.blur();
    }
  }, [open, triggerId]);
  return (
    <div
      {...props}
      ref={ref}
      className={cn("disclosure-content", className)}
      data-open={open}
      aria-hidden={!open}
      inert={!open}
    >
      <div className="min-h-0 overflow-hidden">{visited || !mountOnOpen ? children : null}</div>
    </div>
  );
}
