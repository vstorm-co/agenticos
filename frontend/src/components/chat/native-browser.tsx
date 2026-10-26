"use client";

import { useTranslations } from "next-intl";
import { Maximize2, Minimize2, X } from "lucide-react";
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
    <section className="bg-background flex h-full min-h-0 min-w-0 flex-col">
      <header className="border-border flex shrink-0 flex-wrap items-center gap-2 border-b p-2">
        <BrowserNavigation
          url={state?.url ?? null}
          holding
          send={(command) => {
            if (command.type === "navigate") void send("navigate", command.url);
            else void send(command.type);
          }}
        />
        <button
          type="button"
          className="hover:bg-muted rounded-md px-3 py-2 text-sm"
          onClick={() => void send(state?.held ? "give_back" : "take_over")}
        >
          {state?.held ? t("nativeReturn") : t("nativeTake")}
        </button>
        <button
          type="button"
          className="hover:bg-muted rounded-md px-3 py-2 text-sm"
          onClick={async () => {
            if (await send("close")) onClose();
          }}
        >
          {t("nativeCloseTab")}
        </button>
        {onToggleFullscreen && (
          <button
            type="button"
            className="hover:bg-muted rounded-md p-2"
            aria-label={chat(fullscreen ? "browserDock" : "browserMaximize")}
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
          className="hover:bg-muted rounded-md p-2"
          aria-label={chat("browserClose")}
          onClick={onClose}
        >
          <X className="size-4" aria-hidden />
        </button>
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
