"use client";

import { useEffect, useRef, type ReactNode } from "react";
import { Maximize2, Minimize2, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { BrowserPanelFrame } from "./browser-panel-frame";

/** Files and citations use the same responsive, keyboard-resizable dock as browsing. */
export function ChatSidePanel({
  label,
  panelId,
  contained,
  onClose,
  children,
}: {
  label: string;
  panelId?: string;
  contained: boolean;
  onClose: () => void;
  children: (layout: { fullscreen: boolean; toggleFullscreen: () => void }) => ReactNode;
}) {
  const content = useRef<HTMLDivElement>(null);
  useEffect(() => {
    const previousFocus = document.activeElement;
    const root = content.current;
    const key = (event: KeyboardEvent) => {
      if (event.key !== "Escape" || event.defaultPrevented) return;
      if (event.target instanceof Element && event.target.closest('[role="dialog"], [role="menu"]'))
        return;
      onClose();
    };
    window.addEventListener("keydown", key);
    return () => {
      window.removeEventListener("keydown", key);
      if (
        previousFocus instanceof HTMLElement &&
        previousFocus.isConnected &&
        (root?.contains(document.activeElement) || document.activeElement === document.body)
      )
        previousFocus.focus({ preventScroll: true });
    };
  }, [onClose]);
  return (
    <BrowserPanelFrame label={label} contained={contained} panelId={panelId} layout="sources">
      {(layout) => (
        <div
          ref={content}
          className="flex h-full min-h-0 min-w-0 flex-col"
          data-native-browser-blocked
        >
          {children(layout)}
        </div>
      )}
    </BrowserPanelFrame>
  );
}

/** A quiet title, optional contextual action, expansion and close in a fixed order. */
export function ChatPanelHeader({
  title,
  icon,
  closeLabel,
  onClose,
  fullscreen,
  toggleFullscreen,
  actions,
  subtitle,
  contained = false,
}: {
  title: ReactNode;
  icon: ReactNode;
  closeLabel: string;
  onClose: () => void;
  fullscreen: boolean;
  toggleFullscreen: () => void;
  actions?: ReactNode;
  subtitle?: ReactNode;
  contained?: boolean;
}) {
  const t = useTranslations("chat");
  return (
    <header className="border-border shrink-0 border-b px-4 py-3">
      <div className="flex min-h-8 items-center gap-2">
        <span className="text-muted-foreground shrink-0" aria-hidden>
          {icon}
        </span>
        <h2 className="text-foreground min-w-0 flex-1 truncate text-sm font-medium">{title}</h2>
        {actions}
        {!contained && (
          <>
            <button
              type="button"
              onClick={toggleFullscreen}
              aria-label={t(fullscreen ? "browserDock" : "browserMaximize")}
              className={
                "text-muted-foreground hover:bg-muted hover:text-foreground focus-visible:ring-ring size-8 shrink-0 items-center justify-center rounded-lg outline-none focus-visible:ring-2 " +
                (fullscreen ? "flex" : "hidden @min-[900px]/sources-layout:flex")
              }
            >
              {fullscreen ? (
                <Minimize2 className="size-4" aria-hidden />
              ) : (
                <Maximize2 className="size-4" aria-hidden />
              )}
            </button>
          </>
        )}
        <button
          type="button"
          onClick={onClose}
          aria-label={closeLabel}
          className="text-muted-foreground hover:bg-muted hover:text-foreground focus-visible:ring-ring flex size-8 shrink-0 items-center justify-center rounded-lg outline-none focus-visible:ring-2"
        >
          <X className="size-4" aria-hidden />
        </button>
      </div>
      {subtitle && <p className="text-muted-foreground mt-1 text-xs leading-5">{subtitle}</p>}
    </header>
  );
}
