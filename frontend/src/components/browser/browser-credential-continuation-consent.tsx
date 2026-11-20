"use client";

import { useId, useRef, useState } from "react";
import { useLocale, useTranslations } from "next-intl";
import { Button } from "@/components/ui";
import { browserCredentialDeadlineLive } from "@/lib/browser-credential-review";
import {
  browserContinuationAttemptKey,
  readBrowserContinuationAttempt,
  retainBrowserContinuationAttempt,
} from "@/lib/browser-credential-continuation-attempts";
import type { BrowserContinuationControl } from "@/hooks/use-browser-credential-continuation";
import type { BrowserCredentialPlan } from "@/types/browser-credentials";
import type { BrowserCredentialContinuation } from "@/types/browser-credential-continuation";

export function BrowserContinuationConsent({
  source,
  row,
  control,
}: {
  source: BrowserCredentialPlan;
  row: BrowserCredentialContinuation;
  control: BrowserContinuationControl;
}) {
  const t = useTranslations("browserContinuation");
  const locale = useLocale();
  const keepId = useId();
  const key = browserContinuationAttemptKey(control.audience, source, row);
  const [slot, setSlot] = useState(() => readBrowserContinuationAttempt(key, "confirm"));
  const [keep, setKeep] = useState(false);
  const writing = useRef(false);
  const retained = slot.attempt?.kind === "confirm" ? slot.attempt : null;
  const mismatch =
    retained &&
    (retained.continuation_id !== row.id ||
      retained.document_id !== row.document_id ||
      retained.authorization_generation !== row.authorization_generation);
  const attempt = mismatch ? null : retained;
  const storageUnavailable = slot.unavailable || !!mismatch;
  const live = browserCredentialDeadlineLive(row.expires_at, control.now);
  const available =
    control.current &&
    live &&
    !!row.document_id &&
    !storageUnavailable &&
    !control.confirm.isPending;
  const decide = async (approve: boolean) => {
    if (writing.current || !available || !row.document_id) return;
    writing.current = true;
    const decision = attempt ?? {
      kind: "confirm" as const,
      continuation_id: row.id,
      document_id: row.document_id,
      authorization_generation: row.authorization_generation,
      approve,
      keep_signed_in: approve && keep,
    };
    try {
      if (!retainBrowserContinuationAttempt(key, decision)) {
        setSlot({ attempt: null, unavailable: true });
        return;
      }
      setSlot({ attempt: decision, unavailable: false });
      await control.confirm.mutateAsync({
        row,
        body: {
          document_id: decision.document_id,
          authorization_generation: decision.authorization_generation,
          approve: decision.approve,
          keep_signed_in: decision.keep_signed_in,
        },
      });
    } catch {
      // Never change or silently repeat a decision whose acknowledgement may have been lost.
    } finally {
      writing.current = false;
    }
  };
  return (
    <div className="space-y-3">
      <p>{t("consent")}</p>
      <p className="font-medium break-all">{row.origin}</p>
      <p className="text-muted-foreground text-xs">
        {t("confirmationDeadline")}{" "}
        <time dateTime={row.expires_at}>
          {new Intl.DateTimeFormat(locale, {
            dateStyle: "medium",
            timeStyle: "medium",
          }).format(new Date(row.expires_at))}
        </time>
      </p>
      <div className="flex items-start gap-2">
        <input
          id={keepId}
          type="checkbox"
          aria-describedby={`${keepId}-help`}
          className="mt-1 size-4"
          checked={attempt ? attempt.keep_signed_in : keep}
          disabled={!available || !!attempt}
          onChange={(event) => setKeep(event.target.checked)}
        />
        <div>
          <label htmlFor={keepId} className="block font-medium">
            {t("keepSignedIn")}
          </label>
          <p id={`${keepId}-help`} className="text-muted-foreground text-xs">
            {t("keepDuration")}
          </p>
        </div>
      </div>
      <p className="text-muted-foreground text-xs">{t("accessRechecked")}</p>
      {!live && <p role="status">{t("confirmationExpired")}</p>}
      {attempt && (
        <p role="status">
          {t(attempt.approve ? "continueDecisionRetained" : "declineDecisionRetained")}
        </p>
      )}
      {storageUnavailable && (
        <p role="alert" className="text-destructive">
          {t("storageUnavailable")}
        </p>
      )}
      <div className="flex flex-wrap gap-2">
        {attempt ? (
          <Button size="sm" disabled={!available} onClick={() => void decide(attempt.approve)}>
            {t("retryDecision")}
          </Button>
        ) : (
          <>
            <Button size="sm" disabled={!available} onClick={() => void decide(true)}>
              {t("continueProtected")}
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={!available}
              onClick={() => void decide(false)}
            >
              {t("decline")}
            </Button>
          </>
        )}
      </div>
    </div>
  );
}
