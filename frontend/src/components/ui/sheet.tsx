"use client";

import * as React from "react";
import * as DialogPrimitive from "@radix-ui/react-dialog";
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
  return (
    <DialogPrimitive.Root open={open} onOpenChange={onOpenChange}>
      {children}
    </DialogPrimitive.Root>
  );
}

export function SheetContent({ children, className, side = "left" }: SheetContentProps) {
  const opener = React.useRef<HTMLElement | null>(null);
  return (
    <DialogPrimitive.Portal>
      <DialogPrimitive.Overlay className="data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=open]:fade-in-0 data-[state=closed]:fade-out-0 fixed inset-0 z-50 bg-black/40" />
      <DialogPrimitive.Content
        aria-describedby={undefined}
        onEscapeKeyDown={(event) => {
          // Radix handles Escape during capture, before the input can clear itself.
          const target = event.target;
          if (
            target instanceof HTMLInputElement &&
            target.hasAttribute("data-search-input") &&
            target.value
          )
            event.preventDefault();
        }}
        onOpenAutoFocus={() => {
          // Most sheets are controlled by actions outside a Radix trigger.
          opener.current =
            document.activeElement instanceof HTMLElement ? document.activeElement : null;
        }}
        onCloseAutoFocus={(event) => {
          event.preventDefault();
          if (opener.current?.isConnected) opener.current.focus({ preventScroll: true });
        }}
        // A side panel runs the screen's full height: in the phone app that is
        // under the status bar and over the gesture bar, so it keeps clear of
        // both. Inline, so a caller's own padding (`p-0`) cannot take it away.
        style={
          side === "bottom"
            ? undefined
            : { paddingTop: "var(--shell-inset-top, 0px)", paddingBottom: "var(--safe-bottom)" }
        }
        className={cn(
          "panel-strong fixed z-50 flex min-h-0 max-w-full flex-col overflow-y-auto overscroll-contain outline-none",
          "data-[state=open]:animate-in data-[state=closed]:animate-out duration-200",
          side === "bottom"
            ? "slide-in-from-bottom data-[state=closed]:slide-out-to-bottom inset-x-0 bottom-0 max-h-[calc(var(--app-height,100dvh)-var(--shell-inset-top,0px)-1rem)] rounded-t-2xl pb-[var(--safe-bottom)]"
            : "top-0 h-[var(--app-height,100dvh)] w-72",
          side === "left" && "slide-in-from-left data-[state=closed]:slide-out-to-left left-0",
          side === "right" && "slide-in-from-right data-[state=closed]:slide-out-to-right right-0",
          className,
        )}
      >
        {children}
      </DialogPrimitive.Content>
    </DialogPrimitive.Portal>
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
  return (
    <DialogPrimitive.Title className={cn("text-lg font-semibold", className)}>
      {children}
    </DialogPrimitive.Title>
  );
}

export function SheetClose({ onClick, className }: { onClick: () => void; className?: string }) {
  const t = useTranslations("ui");
  return (
    <button
      type="button"
      onClick={onClick}
      className={cn(
        "ring-offset-background rounded-sm opacity-70 transition-opacity",
        "focus:ring-ring hover:opacity-100 focus:ring-2 focus:ring-offset-2 focus:outline-none",
        "flex h-11 w-11 shrink-0 touch-manipulation items-center justify-center",
        className,
      )}
    >
      <X className="h-5 w-5" />
      <span className="sr-only">{t("close2")}</span>
    </button>
  );
}
