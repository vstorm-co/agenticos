"use client";

import { useEffect } from "react";
import { useRouter } from "next/navigation";
import { useTranslations } from "next-intl";

import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui";
import { DIALOG_CONFIRM } from "@/lib/dialog-sizes";
import { useUnsavedChangesStore } from "@/stores/unsaved-changes-store";

/** Marks the history entry pushed so that Back leaves it before it leaves the page. */
const HELD = "__unsavedHeld";

function heldState(): Record<string, unknown> {
  return { ...(window.history.state as Record<string, unknown> | null), [HELD]: true };
}

/** The address a click on a link would take the page to, when it is a page of this app. */
function inAppTarget(event: MouseEvent): string | null {
  if (event.defaultPrevented || event.button !== 0) return null;
  if (event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return null;
  const anchor = (event.target as Element | null)?.closest?.("a[href]");
  if (!(anchor instanceof HTMLAnchorElement)) return null;
  if ((anchor.target && anchor.target !== "_self") || anchor.hasAttribute("download")) return null;
  const url = new URL(anchor.href, window.location.href);
  // Another site unloads the page, which the browser itself asks about.
  if (url.origin !== window.location.origin) return null;
  if (url.pathname === window.location.pathname && url.search === window.location.search) {
    return null;
  }
  return `${url.pathname}${url.search}${url.hash}`;
}

/**
 * Asks before any way out drops a change somebody has not saved: a link, Back
 * and Forward, closing or reloading the tab, and whatever calls `leave` - a
 * dialog closing, a tab or version changing, another organization chosen.
 *
 * The browser's own dialog is the only one a closing tab allows; everywhere
 * else this one asks, offering Save where the change can be saved from there.
 */
export function UnsavedChangesGuard() {
  const t = useTranslations("unsaved");
  const router = useRouter();
  const prompt = useUnsavedChangesStore((state) => state.prompt);
  const saving = useUnsavedChangesStore((state) => state.saving);
  const answer = useUnsavedChangesStore((state) => state.answer);
  const holding = useUnsavedChangesStore((state) => Object.keys(state.sources).length > 0);
  const canSave = useUnsavedChangesStore(
    (state) =>
      state.prompt !== null &&
      state.prompt.ids.every((id) => state.sources[id]?.save !== undefined),
  );

  useEffect(() => {
    if (!holding) return;
    const hold = (event: BeforeUnloadEvent) => event.preventDefault();
    window.addEventListener("beforeunload", hold);
    return () => window.removeEventListener("beforeunload", hold);
  }, [holding]);

  useEffect(() => {
    if (!holding) return;
    // Capturing, so a link's own handler never starts the navigation being asked about.
    const onClick = (event: MouseEvent) => {
      const target = inAppTarget(event);
      if (target === null) return;
      event.preventDefault();
      event.stopPropagation();
      useUnsavedChangesStore.getState().leave(() => router.push(target));
    };
    document.addEventListener("click", onClick, true);
    return () => document.removeEventListener("click", onClick, true);
  }, [holding, router]);

  useEffect(() => {
    if (!holding) return;
    // A second entry for this same page: Back lands on the first, which shows the
    // same page, and is then asked about. The router reads the copied state as its own.
    if (!(window.history.state as Record<string, unknown> | null)?.[HELD]) {
      window.history.pushState(heldState(), "", window.location.href);
    }
    const onPop = (event: PopStateEvent) => {
      if ((event.state as Record<string, unknown> | null)?.[HELD]) return;
      window.history.pushState(heldState(), "", window.location.href);
      useUnsavedChangesStore.getState().leave(() => window.history.go(-2));
    };
    window.addEventListener("popstate", onPop);
    return () => window.removeEventListener("popstate", onPop);
  }, [holding]);

  return (
    <Dialog
      open={prompt !== null}
      onOpenChange={(open) => {
        if (!open && !saving) void answer("stay");
      }}
    >
      <DialogContent className={DIALOG_CONFIRM}>
        <DialogHeader>
          <DialogTitle>{t("title")}</DialogTitle>
          <DialogDescription>{t(canSave ? "body" : "bodyNoSave")}</DialogDescription>
        </DialogHeader>
        <DialogFooter>
          <Button variant="outline" disabled={saving} onClick={() => void answer("stay")}>
            {t("stay")}
          </Button>
          <Button variant="destructive" disabled={saving} onClick={() => void answer("discard")}>
            {t("discard")}
          </Button>
          {canSave && (
            <Button disabled={saving} onClick={() => void answer("save")}>
              {saving ? t("saving") : t("save")}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
