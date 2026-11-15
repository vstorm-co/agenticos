"use client";

import { useEffect } from "react";
import { Toaster } from "sonner";

/** Keep dismissal in Sonner so actions, promises and onDismiss retain their contract. */
export function ConsoleToaster({ closeLabel }: { closeLabel: string }) {
  useEffect(() => {
    const dismissClicked = (event: MouseEvent) => {
      if (event.defaultPrevented || !(event.target instanceof Element)) return;
      if (event.target.closest("[data-close-button]")) return;
      const item = event.target.closest<HTMLElement>(
        '.console-toasts [data-sonner-toast][data-dismissible="true"]',
      );
      if (!item || item.dataset.type === "loading" || item.dataset.removed === "true") return;
      item.querySelector<HTMLButtonElement>("[data-close-button]")?.click();
    };
    document.addEventListener("click", dismissClicked);
    return () => document.removeEventListener("click", dismissClicked);
  }, []);

  return (
    <Toaster
      closeButton
      className="console-toasts"
      position="top-right"
      gap={8}
      offset={{
        top: "calc(var(--shell-inset-top, 0px) + 1rem)",
        right: "1rem",
        bottom: "5rem",
      }}
      mobileOffset={{
        top: "calc(var(--shell-inset-top, 0px) + 1rem)",
        left: "1rem",
        right: "1rem",
        bottom: "5rem",
      }}
      toastOptions={{
        closeButtonAriaLabel: closeLabel,
        style: {
          borderRadius: "0.875rem",
        },
        classNames: {
          success: "[&_[data-icon]]:text-success",
          error: "[&_[data-icon]]:text-destructive",
          warning: "[&_[data-icon]]:text-warning",
        },
      }}
    />
  );
}
