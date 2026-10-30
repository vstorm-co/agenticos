"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { BellRing } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui";
import { MobileNotificationPreferences } from "@/components/mobile/notification-preferences";
import { IphonePush } from "@/components/mobile/iphone-push";
import { PhonePush } from "@/components/mobile/phone-push";
import { SectionCard } from "@/components/settings/settings-section";
import { useShell } from "@/hooks/use-shell";
import { getErrorMessage } from "@/lib/api-error";
import { disablePush, enablePush, pushState, sendTestPush, type PushState } from "@/lib/web-push";

/**
 * Push notifications in this browser, or the installed web app (#2097): on,
 * off, a test. In the Android app, push through its UnifiedPush distributor
 * instead (`PhonePush`); in the iPhone app, through APNs with the
 * organization's key (`IphonePush`). Absent in the desktop app, which
 * notifies natively while it runs.
 */
export function PushSettings() {
  const shell = useShell();
  if (shell === null) return <PushCard />;
  if (shell.platform === "android")
    return (
      <>
        <PhonePush />
        <MobileNotificationPreferences />
      </>
    );
  return shell.platform === "ios" ? (
    <>
      <IphonePush />
      <MobileNotificationPreferences />
    </>
  ) : null;
}

function PushCard() {
  const t = useTranslations("pages.settings.push");
  const tErrors = useTranslations("errors");
  const [state, setState] = useState<PushState | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let current = true;
    pushState()
      .then((read) => {
        if (current) setState(read);
      })
      .catch(() => {
        if (current) setState("off");
      });
    return () => {
      current = false;
    };
  }, []);

  const act = async (action: () => Promise<void>) => {
    setBusy(true);
    try {
      await action();
    } catch (error) {
      toast.error(getErrorMessage(error, tErrors, t("failed")));
    } finally {
      setBusy(false);
    }
  };

  const turnOn = () => act(async () => setState(await enablePush()));
  const turnOff = () => act(async () => setState(await disablePush()));
  const test = () =>
    act(async () => {
      const result = await sendTestPush();
      if (result.sent > 0) toast.success(t("testSent"));
      else toast.error(t("testNotSent"));
    });

  if (state === null) return null;
  return (
    <SectionCard title={t("title")}>
      <p role="status" className="text-foreground mb-3 text-sm">
        {t(`state.${state}`)}
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <span className="bg-muted text-muted-foreground inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg">
          <BellRing className="h-4 w-4" aria-hidden />
        </span>
        {state === "off" ? (
          <Button onClick={turnOn} disabled={busy}>
            {t("turnOn")}
          </Button>
        ) : null}
        {state === "on" ? (
          <>
            <Button variant="outline" onClick={test} disabled={busy}>
              {t("test")}
            </Button>
            <Button variant="ghost" onClick={turnOff} disabled={busy}>
              {t("turnOff")}
            </Button>
          </>
        ) : null}
      </div>
    </SectionCard>
  );
}
