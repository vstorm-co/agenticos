"use client";

import { useLayoutEffect, useRef, useState, type ComponentPropsWithoutRef } from "react";

import { cn } from "@/lib/utils";

interface DisclosureContentProps extends ComponentPropsWithoutRef<"div"> {
  open: boolean;
  triggerId?: string;
  /** Forms may need to register values before their section is first opened. */
  mountOnOpen?: boolean;
  /** Reveal a collapsed section when native validation needs one of its fields. */
  onReveal?: () => void;
}

/** Keep visited content stable while an interruptible disclosure opens or closes. */
export function DisclosureContent({
  open,
  triggerId,
  mountOnOpen = true,
  onReveal,
  onInvalidCapture,
  children,
  className,
  style,
  ...props
}: DisclosureContentProps) {
  const [visited, setVisited] = useState(open || !mountOnOpen);
  const ref = useRef<HTMLDivElement>(null);
  const invalidField = useRef<HTMLElement | null>(null);
  if (open && !visited) setVisited(true);
  useLayoutEffect(() => {
    if (open && invalidField.current) {
      invalidField.current.focus();
      invalidField.current = null;
    }
    if (!open && ref.current?.contains(document.activeElement)) {
      const trigger = triggerId ? document.getElementById(triggerId) : null;
      if (trigger) trigger.focus({ preventScroll: true });
      else if (document.activeElement instanceof HTMLElement) document.activeElement.blur();
    }
  }, [open, triggerId]);
  return (
    <div
      {...props}
      ref={ref}
      onInvalidCapture={(event) => {
        onInvalidCapture?.(event);
        if (!open && onReveal && !event.defaultPrevented && event.target instanceof HTMLElement) {
          event.preventDefault();
          invalidField.current ??= event.target;
          onReveal();
        }
      }}
      className={cn("disclosure-content", className)}
      style={{ ...style, visibility: open ? "visible" : "hidden" }}
      data-open={open}
      aria-hidden={!open}
      inert={!open}
    >
      <div className="min-h-0 overflow-hidden">{visited || !mountOnOpen ? children : null}</div>
    </div>
  );
}
