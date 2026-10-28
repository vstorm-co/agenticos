"use client";
import { useEffect, useRef, useState, useSyncExternalStore } from "react";
import { useTranslations } from "next-intl";
import {
  Button,
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogFooter,
} from "@/components/ui";
import { useDesktopSetup } from "@/hooks/use-desktop-setup";
import { useShellEvent } from "@/hooks/use-desktop";
import { useDesktopPreferencesStore } from "@/stores/desktop-preferences-store";
import { ReadinessPanel } from "./readiness-panel";
import { useRouter } from "@/lib/locale-navigation";

/** A connection review is per server/account/org and explicit connection revision, never user age. */
export function DesktopSetupGate() {
  const t = useTranslations("desktop.readiness");
  const setup = useDesktopSetup();
  const hydrated = useSyncExternalStore(
    useDesktopPreferencesStore.persist.onFinishHydration,
    useDesktopPreferencesStore.persist.hasHydrated,
    () => false,
  );
  const reviewed = useDesktopPreferencesStore((s) =>
    setup.scope ? s.reviewed[setup.scope] : undefined,
  );
  const mark = useDesktopPreferencesStore((s) => s.review);
  const offered = useRef(new Set<string>());
  const [requestedOpen, setOpen] = useState(false);
  const [repair, setRepair] = useState<string | null>(null);
  const router = useRouter();
  const settled = setup.items.every((item) => item.state !== "checking");
  const needsSetup = setup.items.some((item) => item.state === "missing" || item.state === "error");
  const reviewDue =
    hydrated &&
    settled &&
    !!setup.scope &&
    setup.revision !== undefined &&
    reviewed !== setup.revision;
  const open = requestedOpen || (reviewDue && needsSetup);
  useEffect(() => {
    if (reviewDue && !needsSetup && setup.scope && setup.revision !== undefined)
      mark(setup.scope, setup.revision);
  }, [reviewDue, needsSetup, setup.scope, setup.revision, mark]);
  useShellEvent("desktop:repair-needed", (value) => {
    if (typeof value === "string" && !offered.current.has(value)) {
      offered.current.add(value);
      setRepair(value);
      setOpen(true);
      setup.refresh();
    }
  });
  const close = () => {
    if (setup.scope && setup.revision !== undefined) mark(setup.scope, setup.revision);
    setOpen(false);
  };
  return (
    <>
      {!open && setup.items.some((item) => item.state === "missing" || item.state === "error") && (
        <button
          type="button"
          className="bg-background text-muted-foreground fixed right-4 bottom-4 z-30 rounded-full border px-3 py-2 text-xs shadow-sm"
          onClick={() => router.push("/settings/desktop")}
        >
          {t("remaining", {
            count: setup.items.filter((i) => i.state === "missing" || i.state === "error").length,
          })}
        </button>
      )}
      <Dialog
        open={open}
        onOpenChange={(value) => {
          if (!value) close();
        }}
      >
        <DialogContent className="max-h-[85dvh] overflow-y-auto sm:max-w-xl">
          <DialogHeader>
            <DialogTitle>{t("welcome")}</DialogTitle>
            <DialogDescription>{t("welcomeHint")}</DialogDescription>
          </DialogHeader>
          <ReadinessPanel repair={repair} />
          <DialogFooter>
            <Button variant="outline" onClick={close}>
              {t("later")}
            </Button>
            <Button onClick={close}>{t("done")}</Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </>
  );
}
