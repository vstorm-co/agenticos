"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { BellRing } from "lucide-react";
import { toast } from "sonner";

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

  useEffect(() => {
    let current = true;
    phonePushStatus()
      .then((read) => {
        if (current) setStatus(read);
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

  if (status === null) return null;
  const on = status.subscription !== null;
  const state = on
    ? "on"
    : status.distributors.length === 0
      ? "noDistributor"
      : status.failed
        ? "failed"
        : "off";

  return (
    <SectionCard
      title={t("title")}
      description={t(state, { distributor: status.distributor ?? "" })}
    >
      <div className="flex flex-wrap items-center gap-2">
        <span className="bg-muted text-muted-foreground inline-flex h-9 w-9 shrink-0 items-center justify-center rounded-lg">
          <BellRing className="h-4 w-4" aria-hidden />
        </span>
        {!on && status.distributors.length > 0 ? (
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
              onClick={() => act(async () => setStatus(await disablePhonePush(status)))}
            >
              {t("turnOff")}
            </Button>
          </>
        ) : null}
      </div>
    </SectionCard>
  );
}
