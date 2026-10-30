"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { BellRing } from "lucide-react";
import { toast } from "sonner";

import { invokeShell } from "@/lib/desktop/shell";
import { Button } from "@/components/ui";
import { SectionCard } from "@/components/settings/settings-section";
import { getErrorMessage } from "@/lib/api-error";
import {
  disablePhonePush,
  enablePhonePush,
  phonePushStatus,
  type PhonePushStatus,
} from "@/lib/mobile/push";
import { sendTestPush } from "@/lib/web-push";

/**
 * Notifications while the phone app is closed (#2097), through a UnifiedPush
 * distributor - ntfy - instead of Google's servers: which one, on or off, a
 * test. With no distributor on the phone, it says what to install.
 */
export function PhonePush() {
  const t = useTranslations("pages.settings.push.phone");
  const tPush = useTranslations("pages.settings.push");
  const tErrors = useTranslations("errors");
  const [status, setStatus] = useState<PhonePushStatus | null>(null);
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);
  const tSetup = useTranslations("mobile.setup");

  useEffect(() => {
    let current = true;
    const refresh = () => {
      setFailed(false);
      phonePushStatus()
        .then((read) => {
          if (current) setStatus(read);
        })
        .catch((error: unknown) => {
          if (current) {
            setFailed(true);
            toast.error(getErrorMessage(error, tErrors, tPush("failed")));
          }
        });
    };
    const visible = () => {
      if (document.visibilityState === "visible") refresh();
    };
    refresh();
    document.addEventListener("visibilitychange", visible);
    window.addEventListener("mobile:push-refresh", refresh);
    return () => {
      current = false;
      document.removeEventListener("visibilitychange", visible);
      window.removeEventListener("mobile:push-refresh", refresh);
    };
  }, [tErrors, tPush]);

  const act = async (action: () => Promise<void>) => {
    setBusy(true);
    try {
      await action();
      window.dispatchEvent(new Event("mobile:push-changed"));
    } catch (error) {
      toast.error(getErrorMessage(error, tErrors, tPush("failed")));
    } finally {
      setBusy(false);
    }
  };

  if (status === null || failed)
    return (
      <SectionCard title={t("title")}>
        <p role="status" className="text-muted-foreground text-sm">
          {tSetup(failed ? "error" : "checking")}
        </p>
        {failed && (
          <Button
            variant="outline"
            onClick={() => window.dispatchEvent(new Event("mobile:push-refresh"))}
          >
            {tSetup("retry")}
          </Button>
        )}
      </SectionCard>
    );
  const on =
    status.subscription !== null &&
    (status.permission === undefined || status.permission === "granted");
  const state =
    status.permission === "denied"
      ? "denied"
      : on
        ? "on"
        : status.distributors.length === 0
          ? "noDistributor"
          : status.failed
            ? "failed"
            : "off";

  return (
    <SectionCard title={t("title")}>
      <p role="status" className="text-foreground mb-3 text-sm">
        {t(state, { distributor: status.distributor ?? "" })}
      </p>
      <div className="flex flex-wrap items-center gap-2">
        <span className="bg-muted text-muted-foreground inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg">
          <BellRing className="h-4 w-4" aria-hidden />
        </span>
        {state === "denied" ? (
          <Button
            variant="outline"
            disabled={busy}
            onClick={() =>
              act(async () => {
                await invokeShell("open_mobile_settings");
              })
            }
          >
            {tSetup("systemSettings")}
          </Button>
        ) : null}
        {state === "noDistributor" ? (
          <>
            <Button variant="outline" asChild>
              <a href="https://ntfy.sh/docs/subscribe/phone/" target="_blank" rel="noreferrer">
                {tSetup("installDistributor")}
              </a>
            </Button>
            <Button
              variant="ghost"
              onClick={() => window.dispatchEvent(new Event("mobile:push-refresh"))}
            >
              {tSetup("retry")}
            </Button>
          </>
        ) : null}
        {!on && state !== "denied" && status.distributors.length > 0 ? (
          <Button
            disabled={busy}
            onClick={() =>
              act(async () => {
                const next = await enablePhonePush();
                setStatus(next);
                if (!next.subscription) toast.error(t("notRegistered"));
              })
            }
          >
            {tPush("turnOn")}
          </Button>
        ) : null}
        {on ? (
          <>
            <Button
              variant="outline"
              disabled={busy}
              onClick={() =>
                act(async () => {
                  const result = await sendTestPush();
                  if (result.sent > 0) toast.success(tSetup("testAccepted"));
                  else toast.error(tPush("testNotSent"));
                })
              }
            >
              {tPush("test")}
            </Button>
            <Button
              variant="ghost"
              disabled={busy}
              onClick={() => act(async () => setStatus(await disablePhonePush(status)))}
            >
              {t("turnOff")}
            </Button>
          </>
        ) : null}
      </div>
      <p className="text-muted-foreground mt-3 text-xs">{tSetup("testHint")}</p>
    </SectionCard>
  );
}
