"use client";

import { forwardRef, type ComponentPropsWithoutRef } from "react";
import { cn } from "@/lib/utils";

/** Native disclosure semantics and persistent content, with the shared presentation. */
export const NativeDisclosure = forwardRef<HTMLDetailsElement, ComponentPropsWithoutRef<"details">>(
  ({ className, ...props }, ref) => (
    <details ref={ref} className={cn("native-disclosure", className)} {...props} />
  ),
);
NativeDisclosure.displayName = "NativeDisclosure";
