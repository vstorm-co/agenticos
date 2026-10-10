"use client";

import * as React from "react";
import { createPortal } from "react-dom";
import { cn } from "@/lib/utils";
import { X } from "lucide-react";
import { useTranslations } from "next-intl";

interface SheetProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  children: React.ReactNode;
}

interface SheetContentProps {
  children: React.ReactNode;
  className?: string;
  /** `bottom` is a phone's action sheet - full width, up from the bottom edge. */
  side?: "left" | "right" | "bottom";
}

export function Sheet({ open, onOpenChange, children }: SheetProps) {
  React.useEffect(() => {
    if (open) {
      document.body.style.overflow = "hidden";
    } else {
      document.body.style.overflow = "";
    }
    return () => {
      document.body.style.overflow = "";
    };
  }, [open]);

  if (!open) return null;

  // On `body`, not where it is declared: a sheet opened from inside a panel that
  // makes its own stacking context - the chat's composer dock - otherwise sits
  // under the fixed tab bar and the assistant's button, whatever its z-index.
  return createPortal(
    <div className="fixed inset-0 z-50">
      <div
        className="fixed inset-0 bg-black/50 backdrop-blur-sm"
        onClick={() => onOpenChange(false)}
        aria-hidden="true"
      />
      {children}
    </div>,
    document.body,
  );
}

export function SheetContent({ children, className, side = "left" }: SheetContentProps) {
  return (
    <div
      // A modal panel is a dialog to assistive tech, and the role is also what
      // lets a test scope its queries to the panel rather than the page it
      // covers - the run drawer renders a second table over the list's.
      role="dialog"
      aria-modal="true"
      className={cn(
        "panel-strong fixed z-50 flex flex-col",
        "animate-in duration-300",
        side === "bottom"
          ? "slide-in-from-bottom inset-x-0 bottom-0 rounded-t-2xl pb-[env(safe-area-inset-bottom)]"
          : "inset-y-0 w-72",
        side === "left" && "slide-in-from-left left-0",
        side === "right" && "slide-in-from-right right-0",
        className,
      )}
    >
      {children}
    </div>
  );
}

export function SheetHeader({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div className={cn("flex items-center justify-between border-b p-4", className)}>
      {children}
    </div>
  );
}

export function SheetTitle({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return <h2 className={cn("text-lg font-semibold", className)}>{children}</h2>;
}

export function SheetClose({ onClick, className }: { onClick: () => void; className?: string }) {
  const t = useTranslations("ui");
  return (
    <button
      onClick={onClick}
      className={cn(
        "ring-offset-background rounded-sm opacity-70 transition-opacity",
        "focus:ring-ring hover:opacity-100 focus:ring-2 focus:ring-offset-2 focus:outline-none",
        "flex h-10 w-10 items-center justify-center",
        className,
      )}
    >
      <X className="h-5 w-5" />
      <span className="sr-only">{t("close2")}</span>
    </button>
  );
}
