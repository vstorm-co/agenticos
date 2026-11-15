"use client";

import { Globe, Monitor, X } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { workspaceWebsite, type workspaceStartReason } from "@/lib/workspace-panels";
import { useBrowserPanelStore, type BrowseSurface } from "@/stores/browser-panel-store";
import { BrowserPanelFrame } from "./browser-panel-frame";

export type WorkspaceRefusal = ReturnType<typeof workspaceStartReason>;

/** An idle pane is useful before there is a run; only submitting asks the agent to start. */
export function WorkspaceEmpty({
  surface,
  reason,
  onStart,
  panelId,
}: {
  surface: BrowseSurface;
  reason: WorkspaceRefusal;
  onStart?: (surface: BrowseSurface, url?: string) => void;
  panelId?: string;
}) {
  const t = useTranslations("chat.workspace");
  const close = useBrowserPanelStore((state) => state.close);
  const [website, setWebsite] = useState("");
  const [invalid, setInvalid] = useState(false);
  const Icon = surface === "browser" ? Globe : Monitor;
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      if (
        event.key === "Escape" &&
        !event.defaultPrevented &&
        !(
          event.target instanceof HTMLElement &&
          event.target.closest('[role="menu"], [role="dialog"]')
        )
      )
        close();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [close]);
  return (
    <BrowserPanelFrame id={panelId} label={t(surface)} resizeLabel={t("resize")}>
      {() => (
        <>
          <div className="border-border flex items-center gap-2 border-b p-3">
            <Icon className="size-4" aria-hidden />
            <h2 className="flex-1 text-sm font-medium">{t(surface)}</h2>
            <button
              type="button"
              onClick={close}
              aria-label={t("close")}
              className="hover:bg-muted rounded-md p-1.5"
            >
              <X className="size-4" aria-hidden />
            </button>
          </div>
          <form
            noValidate
            className="m-auto flex w-full max-w-sm flex-col gap-4 p-6"
            onSubmit={(event) => {
              event.preventDefault();
              if (reason !== null || !onStart) return;
              const url = surface === "browser" ? workspaceWebsite(website) : undefined;
              if (url === null) {
                setInvalid(true);
                return;
              }
              setInvalid(false);
              onStart(surface, url);
            }}
          >
            <Icon className="text-muted-foreground size-8" aria-hidden />
            <p className="text-muted-foreground text-sm leading-relaxed">
              {t(surface === "browser" ? "browserEmpty" : "computerEmpty")}
            </p>
            {surface === "browser" && (
              <label className="space-y-2 text-sm">
                <span>{t("website")}</span>
                <Input
                  type="url"
                  value={website}
                  autoComplete="url"
                  placeholder={t("websitePlaceholder")}
                  aria-invalid={invalid}
                  onChange={(event) => {
                    setWebsite(event.target.value);
                    setInvalid(false);
                  }}
                />
              </label>
            )}
            {invalid && (
              <p role="alert" className="text-destructive text-sm">
                {t("websiteInvalid")}
              </p>
            )}
            {reason && (
              <p role="status" className="text-muted-foreground text-sm">
                {t(reason)}
              </p>
            )}
            {onStart && reason !== "readOnly" && (
              <Button type="submit" disabled={reason !== null}>
                {t(surface === "browser" ? "startBrowser" : "startComputer")}
              </Button>
            )}
          </form>
        </>
      )}
    </BrowserPanelFrame>
  );
}
