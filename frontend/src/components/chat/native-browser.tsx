"use client";

import { useTranslations } from "next-intl";
import { Hand, Maximize2, Minimize2, PanelRightClose, Undo2, X } from "lucide-react";
import { useNativeBrowser } from "@/hooks/use-native-browser";
import { BrowserNavigation } from "./browser-navigation";

/** The page below this toolbar is an operating-system WebView, without image transport. */
export function NativeBrowser({
  id,
  onClose,
  fullscreen = false,
  onToggleFullscreen,
}: {
  id: string;
  onClose: () => void;
  fullscreen?: boolean;
  onToggleFullscreen?: () => void;
}) {
  const t = useTranslations("browse");
  const chat = useTranslations("chat");
  const { viewport, state, error, send } = useNativeBrowser(id);
  return (
    <section className="bg-background @container/browser-window flex h-full min-h-0 min-w-0 flex-col">
      <header className="bg-muted/25 border-border flex shrink-0 flex-wrap items-center gap-1.5 border-b p-1.5 @min-[640px]/browser-window:flex-nowrap">
        <div className="flex min-w-0 flex-1 basis-full @min-[640px]/browser-window:basis-auto">
          <BrowserNavigation
            url={state?.url ?? null}
            holding
            send={(command) => {
              if (command.type === "navigate") void send("navigate", command.url);
              else void send(command.type);
            }}
          />
        </div>
        <div className="ml-auto flex shrink-0 items-center gap-0.5">
          <button
            type="button"
            aria-label={state?.held ? t("nativeReturn") : t("nativeTake")}
            title={state?.held ? t("nativeReturn") : t("nativeTake")}
            className="bg-foreground text-background hover:bg-foreground/90 flex h-8 items-center gap-1.5 rounded-lg px-2 text-xs font-medium @min-[480px]/browser-window:px-3"
            onClick={() => void send(state?.held ? "give_back" : "take_over")}
          >
            {state?.held ? (
              <Undo2 className="size-4" aria-hidden />
            ) : (
              <Hand className="size-4" aria-hidden />
            )}
            <span className="hidden @min-[480px]/browser-window:inline">
              {state?.held ? t("nativeReturn") : t("nativeTake")}
            </span>
          </button>
          <button
            type="button"
            className="text-muted-foreground hover:text-foreground hover:bg-muted flex size-8 items-center justify-center rounded-lg"
            aria-label={t("nativeCloseTab")}
            title={t("nativeCloseTab")}
            onClick={async () => {
              if (await send("close")) onClose();
            }}
          >
            <X className="size-4" aria-hidden />
          </button>
          {onToggleFullscreen && (
            <button
              type="button"
              className="text-muted-foreground hover:text-foreground hover:bg-muted flex size-8 items-center justify-center rounded-lg"
              aria-label={chat(fullscreen ? "browserDock" : "browserMaximize")}
              title={chat(fullscreen ? "browserDock" : "browserMaximize")}
              onClick={onToggleFullscreen}
            >
              {fullscreen ? (
                <Minimize2 className="size-4" aria-hidden />
              ) : (
                <Maximize2 className="size-4" aria-hidden />
              )}
            </button>
          )}
          <button
            type="button"
            className="text-muted-foreground hover:text-foreground hover:bg-muted flex size-8 items-center justify-center rounded-lg"
            aria-label={chat("browserClose")}
            title={chat("browserClose")}
            onClick={onClose}
          >
            <PanelRightClose className="size-4" aria-hidden />
          </button>
        </div>
      </header>
      {error && (
        <p role="alert" className="text-destructive shrink-0 px-3 py-2 text-sm">
          {error}
        </p>
      )}
      <div ref={viewport} className="min-h-0 flex-1" aria-label={t("nativeViewport")} />
    </section>
  );
}
