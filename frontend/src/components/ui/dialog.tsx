"use client";

import * as React from "react";
import * as DialogPrimitive from "@radix-ui/react-dialog";
import { X } from "lucide-react";
import { cn } from "@/lib/utils";
import { useTranslations } from "next-intl";

const Dialog = DialogPrimitive.Root;
const DialogTrigger = DialogPrimitive.Trigger;
const DialogPortal = DialogPrimitive.Portal;
const DialogClose = DialogPrimitive.Close;

const DialogOverlay = React.forwardRef<
  React.ComponentRef<typeof DialogPrimitive.Overlay>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Overlay>
>(({ className, ...props }, ref) => (
  <DialogPrimitive.Overlay
    ref={ref}
    className={cn(
      // A veil rather than a blackout: the page stays legible enough to say where
      // the dialog came from without blurring an entire scrolling viewport.
      "data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 fixed inset-0 z-50 bg-black/40 duration-150",
      className,
    )}
    {...props}
  />
));
DialogOverlay.displayName = DialogPrimitive.Overlay.displayName;

const DialogContent = React.forwardRef<
  React.ComponentRef<typeof DialogPrimitive.Content>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Content>
>(({ className, children, onInteractOutside, onEscapeKeyDown, ...props }, ref) => {
  const t = useTranslations("common");
  return (
    <DialogPortal>
      <DialogOverlay />
      <DialogPrimitive.Content
        ref={ref}
        onInteractOutside={(event) => {
          onInteractOutside?.(event);
          // While the onboarding coach is guiding this dialog, its freeze is the whole
          // point — the reader operates only the field being pointed at. Radix would
          // dismiss on any outside interaction (the backdrop, or the coach's own card,
          // which sits outside the dialog), stranding the walk on a step whose dialog
          // is gone. Keep it open; the coach's close button ends the walk, and the
          // dialog's own Cancel still closes it. A no-op when no coach is active
          // (`[data-coach-card]` renders only while a flow runs). The check is global
          // on purpose: while any flow runs — a `roam` step included, where the page
          // is fully interactive — every dialog in the app ignores Escape and
          // outside-click, not only the one being guided. Deliberate, and X and Cancel
          // still close, so nobody is trapped.
          if (document.querySelector("[data-coach-card]")) event.preventDefault();
        }}
        onEscapeKeyDown={(event) => {
          onEscapeKeyDown?.(event);
          const target = event.target;
          if (
            target instanceof HTMLInputElement &&
            target.hasAttribute("data-search-input") &&
            target.value
          )
            event.preventDefault();
          // Escape strands the coach the same way an outside click does — block it too
          // while a flow is guiding this dialog.
          if (document.querySelector("[data-coach-card]")) event.preventDefault();
        }}
        className={cn(
          // Solid, unlike the drawers and menus: a centred modal sits directly
          // over the dimmed page, and any translucency reads as a stain of
          // whatever happens to be behind it - the wrong place for panel.
          // Rises a few pixels as it scales in, and settles with a spring - the
          // motion of something placed in front of the page, not faded onto it.
          "bg-card data-[state=open]:animate-in data-[state=closed]:animate-out data-[state=closed]:fade-out-0 data-[state=open]:fade-in-0 data-[state=closed]:zoom-out-95 data-[state=open]:zoom-in-95 data-[state=open]:slide-in-from-bottom-2 border-foreground/10 fixed top-[var(--dialog-center)] left-[50%] z-50 grid max-h-[var(--dialog-available-height)] w-[calc(100%-1.5rem)] max-w-lg translate-x-[-50%] translate-y-[-50%] gap-4 overflow-y-auto overscroll-contain rounded-2xl border p-5 shadow-[0_32px_80px_-24px_oklch(0%_0_0/0.45),0_2px_8px_oklch(0%_0_0/0.08)] duration-300 data-[state=closed]:duration-150 data-[state=open]:ease-[var(--ease-spring)] sm:rounded-2xl sm:p-6",
          className,
        )}
        {...props}
      >
        {children}
        <DialogPrimitive.Close className="text-muted-foreground hover:text-foreground hover:bg-accent focus-visible:ring-ring touch:min-h-11 touch:min-w-11 absolute top-2 right-2 flex size-11 touch-manipulation items-center justify-center rounded-xl transition-colors duration-150 focus:outline-none focus-visible:ring-2 disabled:pointer-events-none sm:size-9">
          <X className="h-4 w-4" />
          <span className="sr-only">{t("close")}</span>
        </DialogPrimitive.Close>
      </DialogPrimitive.Content>
    </DialogPortal>
  );
});
DialogContent.displayName = DialogPrimitive.Content.displayName;

function DialogHeader({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      // Clear of the close button in the corner, which a long title ran under.
      // One unprefixed class, so a caller's own padding replaces it whole.
      className={cn("flex flex-col space-y-1.5 pr-10 text-left", className)}
      {...props}
    />
  );
}

function DialogFooter({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      // A rule above the actions, so where the form ends and the decision starts
      // is drawn rather than implied by a gap.
      className={cn(
        "border-border mt-1 flex flex-col-reverse gap-2 border-t pt-4 sm:flex-row sm:justify-end",
        className,
      )}
      {...props}
    />
  );
}

const DialogTitle = React.forwardRef<
  React.ComponentRef<typeof DialogPrimitive.Title>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Title>
>(({ className, ...props }, ref) => (
  <DialogPrimitive.Title
    ref={ref}
    className={cn("text-lg leading-tight font-semibold tracking-tight", className)}
    {...props}
  />
));
DialogTitle.displayName = DialogPrimitive.Title.displayName;

const DialogDescription = React.forwardRef<
  React.ComponentRef<typeof DialogPrimitive.Description>,
  React.ComponentPropsWithoutRef<typeof DialogPrimitive.Description>
>(({ className, ...props }, ref) => (
  <DialogPrimitive.Description
    ref={ref}
    className={cn("text-muted-foreground text-[13px] leading-relaxed", className)}
    {...props}
  />
));
DialogDescription.displayName = DialogPrimitive.Description.displayName;

export {
  Dialog,
  DialogPortal,
  DialogOverlay,
  DialogClose,
  DialogTrigger,
  DialogContent,
  DialogHeader,
  DialogFooter,
  DialogTitle,
  DialogDescription,
};
