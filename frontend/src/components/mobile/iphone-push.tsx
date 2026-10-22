"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { BellRing } from "lucide-react";
import { toast } from "sonner";

import { Button } from "@/components/ui";
import { SectionCard } from "@/components/settings/settings-section";
import { getErrorMessage } from "@/lib/api-error";
import {
  disableIphonePush,
  enableIphonePush,
  iphonePush,
  type IphonePush as IphonePushState,
} from "@/lib/mobile/apns";
import { sendTestPush } from "@/lib/web-push";

/**
 * Notifications while the iPhone app is closed (#2097), through Apple's push
 * service with the organization's own key: on or off, a test. Without the
 * key it says an administrator has to add one; turned off in iOS Settings, it
 * says where to turn it back on.
 */
export function IphonePush() {
  const t = useTranslations("pages.settings.push.iphone");
  const tPush = useTranslations("pages.settings.push");
  const tErrors = useTranslations("errors");
  const [push, setPush] = useState<IphonePushState | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let current = true;
    iphonePush()
      .then((read) => {
        if (current) setPush(read);
      })
      .catch((error: unknown) => toast.error(getErrorMessage(error, tErrors, tPush("failed"))));
    return () => {
      current = false;
    };
  }, [tErrors, tPush]);

  const act = async (action: () => Promise<void>) => {
    setBusy(true);
    try {
      await action();
    } catch (error) {
      toast.error(getErrorMessage(error, tErrors, tPush("failed")));
    } finally {
      setBusy(false);
    }
  };

  if (push === null) return null;
  const on = push.permission === "granted" && push.token !== null;
  const state = !push.configured
    ? "notConfigured"
    : push.permission === "denied"
      ? "denied"
      : on
        ? "on"
        : "off";

  return (
    <SectionCard title={t("title")} description={t(state)}>
      <div className="flex flex-wrap items-center gap-2">
        <span className="bg-muted text-muted-foreground inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg">
          <BellRing className="h-4 w-4" aria-hidden />
        </span>
        {state === "off" ? (
          <Button
            disabled={busy}
            onClick={() =>
              act(async () => {
                const next = await enableIphonePush();
                setPush(next);
                if (next.permission === "denied") toast.error(t("denied"));
              })
            }
          >
            {tPush("turnOn")}
          </Button>
        ) : null}
        {state === "on" ? (
          <>
            <Button
              variant="outline"
              disabled={busy}
              onClick={() =>
                act(async () => {
                  const result = await sendTestPush();
                  if (result.sent > 0) toast.success(tPush("testSent"));
                  else toast.error(tPush("testNotSent"));
                })
              }
            >
              {tPush("test")}
            </Button>
            <Button
              variant="ghost"
              disabled={busy}
              onClick={() => act(async () => setPush(await disableIphonePush(push)))}
            >
              {t("turnOff")}
            </Button>
          </>
        ) : null}
      </div>
    </SectionCard>
  );
}
