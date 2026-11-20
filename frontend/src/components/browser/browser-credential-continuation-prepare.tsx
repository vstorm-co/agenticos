"use client";

import { useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { Button } from "@/components/ui";
import {
  browserContinuationAttemptKey,
  readBrowserContinuationAttempt,
  retainBrowserContinuationAttempt,
} from "@/lib/browser-credential-continuation-attempts";
import type { BrowserContinuationControl } from "@/hooks/use-browser-credential-continuation";
import type { BrowserCredentialPlan } from "@/types/browser-credentials";

export function BrowserContinuationPrepare({
  source,
  control,
}: {
  source: BrowserCredentialPlan;
  control: BrowserContinuationControl;
}) {
  const t = useTranslations("browserContinuation");
  const key = browserContinuationAttemptKey(control.audience, source);
  const [slot, setSlot] = useState(() => readBrowserContinuationAttempt(key, "prepare"));
  const writing = useRef(false);
  const available =
    control.current && control.row === null && !slot.unavailable && !control.prepare.isPending;
  const prepare = async () => {
    if (writing.current || !available) return;
    writing.current = true;
    try {
      const attempt = slot.attempt ?? { kind: "prepare" as const, request_id: crypto.randomUUID() };
      if (attempt.kind !== "prepare" || !retainBrowserContinuationAttempt(key, attempt)) {
        setSlot({ attempt: null, unavailable: true });
        return;
      }
      setSlot({ attempt, unavailable: false });
      await control.prepare.mutateAsync({ request_id: attempt.request_id });
    } catch {
      // The original request remains retained; only a read can reconcile an uncertain response.
      setSlot(readBrowserContinuationAttempt(key, "prepare"));
    } finally {
      writing.current = false;
    }
  };
  return (
    <div className="space-y-3">
      <p className="text-muted-foreground">{t("preparationOnly")}</p>
      {slot.attempt && <p role="status">{t("preparationRetained")}</p>}
      {slot.unavailable && (
        <p role="alert" className="text-destructive">
          {t("storageUnavailable")}
        </p>
      )}
      <Button size="sm" disabled={!available} onClick={() => void prepare()}>
        {t(slot.attempt ? "retryPreparation" : "prepare")}
      </Button>
    </div>
  );
}
