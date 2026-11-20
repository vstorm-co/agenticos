"use client";

import { useLayoutEffect, useRef, useState } from "react";
import { ExternalLink, Lock } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { Button } from "@/components/ui";
import { useBrowserCredentialAudience } from "@/hooks/use-browser-credentials";
import { useBrowserCredentialPlan } from "@/hooks/use-browser-credential-plan";
import { isBrowserContinuationSource } from "@/lib/browser-credential-continuation";
import {
  browserCredentialDeadlineLive,
  browserCredentialFields,
  browserCredentialOrigin,
  browserCredentialPending,
  browserCredentialSubmissionMatches,
  browserSubmissionKey,
  currentBrowserCredential,
  isBrowserCredentialId,
  readBrowserSubmissionAttempt,
  retainBrowserSubmissionAttempt,
} from "@/lib/browser-credential-review";
import type { BrowserCredentialPlan, BrowserCredentialState } from "@/types/browser-credentials";
import { BrowserCredentialContinuationPanel } from "./browser-credential-continuation";

interface ReviewProps {
  runId: string;
  planId: string;
  callId?: string;
  tabId?: string;
  continuationId?: string;
  onProtected?: () => void;
}
const STATES: readonly BrowserCredentialState[] = [
  "requested",
  "preparing",
  "awaiting_confirmation",
  "approved",
  "claimed",
  "filled",
  "submitted",
  "refused",
  "unknown",
  "expired",
  "declined",
];

/** Keys discard private query/mutation state whenever the audience or addressed receipt changes. */
export function BrowserCredentialReview(props: ReviewProps) {
  const audience = useBrowserCredentialAudience();
  return (
    <CredentialReview
      key={JSON.stringify([
        audience.actor,
        audience.organization,
        props.runId,
        props.planId,
        props.callId,
        props.tabId,
        props.continuationId,
      ])}
      {...props}
    />
  );
}

function CredentialReview({
  runId,
  planId,
  callId,
  tabId,
  continuationId,
  onProtected,
}: ReviewProps) {
  const t = useTranslations("browserCredentials");
  const state = useBrowserCredentialPlan(runId, planId, callId, tabId);
  const { plan, submission } = state;
  const child =
    plan && submission.data && browserCredentialSubmissionMatches(plan, submission.data)
      ? submission.data
      : null;
  const protectedOutput = plan?.output_protected || child?.output_protected;
  useLayoutEffect(() => {
    if (protectedOutput) onProtected?.();
  }, [protectedOutput, onProtected]);

  if (!plan || (continuationId !== undefined && !isBrowserContinuationSource(plan)))
    return (
      <section aria-label={t("reviewTitle")} className="space-y-3 p-4">
        <h3 className="font-medium">{t("reviewTitle")}</h3>
        <p
          role={state.receipt.isPending && state.ready ? "status" : "alert"}
          className="text-muted-foreground text-sm"
        >
          {state.receipt.isPending && state.ready ? t("loadingPlan") : t("planUnavailable")}
        </p>
        <Button
          variant="outline"
          size="sm"
          disabled={!state.ready || state.receipt.isFetching}
          onClick={() => void state.refresh()}
        >
          {t("checkAgain")}
        </Button>
      </section>
    );

  return (
    <CredentialReceipt
      key={JSON.stringify([plan.id, plan.authorization_generation, plan.document_id])}
      state={state}
      plan={plan}
      child={child}
      continuationId={continuationId}
    />
  );
}

function ReceiptStatus({ plan }: { plan: BrowserCredentialPlan }) {
  const t = useTranslations("browserCredentials");
  const status = STATES.includes(plan.state) ? plan.state : "unknown";
  const reason =
    plan.reason_code && t.has(`reasons.${plan.reason_code}`)
      ? t(`reasons.${plan.reason_code}`)
      : null;
  return (
    <div className="space-y-1">
      <p role="status" className="font-medium" data-testid="browser-credential-state">
        {t(`states.${status}`)}
      </p>
      {reason && <p className="text-muted-foreground text-sm">{reason}</p>}
      {status === "unknown" && (
        <p className="text-muted-foreground text-sm">{t("unknownOutcome")}</p>
      )}
      {status === "submitted" && (
        <p className="text-muted-foreground text-sm">{t("submittedReceipt")}</p>
      )}
    </div>
  );
}

function Deadline({ value }: { value: string | null }) {
  const locale = useLocale();
  const t = useTranslations("browserCredentials");
  if (!value || !Number.isFinite(Date.parse(value))) return <span>{t("deadlineUnavailable")}</span>;
  return (
    <time dateTime={value}>
      {new Intl.DateTimeFormat(locale, {
        dateStyle: "medium",
        timeStyle: "medium",
      }).format(new Date(value))}
    </time>
  );
}

function CredentialReceipt({
  state,
  plan,
  child,
  continuationId,
}: {
  state: ReturnType<typeof useBrowserCredentialPlan>;
  plan: BrowserCredentialPlan;
  child: BrowserCredentialPlan | null;
  continuationId?: string;
}) {
  const t = useTranslations("browserCredentials");
  const slotKey = browserSubmissionKey(state.audience, plan);
  const [slot, setSlot] = useState(() => readBrowserSubmissionAttempt(slotKey, plan));
  const [needsRecovery, setNeedsRecovery] = useState(false);
  const [busy, setBusy] = useState(false);
  const writing = useRef(false);
  const origin = browserCredentialOrigin(plan.origin);
  const fields = browserCredentialFields(plan);
  const eligible = !state.eligibility.isError
    ? currentBrowserCredential(plan, state.eligibility.data)
    : null;
  const receiptCurrent = !state.receipt.isError && !state.receipt.isFetching && !state.pollingEnded;
  const eligibleCurrent = !!eligible && !state.eligibility.isFetching;
  const exactDocument = isBrowserCredentialId(plan.document_id) && !!origin && !!fields;
  const waitingForFill = plan.operation === "fill" && plan.state === "awaiting_confirmation";
  const fillLive = browserCredentialDeadlineLive(plan.expires_at, state.now);
  const filled = plan.operation === "fill" && plan.state === "filled";
  const submitLive = browserCredentialDeadlineLive(plan.submission_expires_at, state.now);
  const recoveryCurrent =
    state.submission.isFetchedAfterMount &&
    !state.submission.isError &&
    !state.submission.isFetching &&
    state.submission.data === null &&
    !needsRecovery;
  const invalidChild = !!state.submission.data && !child;
  const canConfirm =
    waitingForFill && fillLive && exactDocument && receiptCurrent && eligibleCurrent && !busy;
  const canDecline = waitingForFill && fillLive && exactDocument && receiptCurrent && !busy;
  const canSubmit =
    filled &&
    submitLive &&
    exactDocument &&
    receiptCurrent &&
    eligibleCurrent &&
    recoveryCurrent &&
    !slot.unavailable &&
    !invalidChild &&
    !busy;
  const handoff =
    origin &&
    (plan.output_protected ||
      child?.output_protected ||
      ["awaiting_confirmation", "approved", "claimed", "filled", "submitted"].includes(plan.state));

  const confirm = async (approve: boolean) => {
    if (writing.current || !(approve ? canConfirm : canDecline)) return;
    writing.current = true;
    setBusy(true);
    try {
      await state.confirm.mutateAsync({ receipt: plan, approve });
    } catch {
      /* The receipt read reconciles the result; no automatic confirmation retry. */
    } finally {
      writing.current = false;
      setBusy(false);
    }
  };
  const submit = async () => {
    if (writing.current || !canSubmit) return;
    writing.current = true;
    setBusy(true);
    try {
      let attempt;
      try {
        attempt = retainBrowserSubmissionAttempt(slotKey, plan);
        setSlot({ attempt, unavailable: false });
      } catch {
        setSlot({ attempt: null, unavailable: true });
        return;
      }
      setNeedsRecovery(true);
      try {
        await state.submit.mutateAsync({ parent: plan, attempt });
      } catch {
        // A failed acknowledgement can still have committed. Reconcile with GET only.
        const result = await state.submission.refetch();
        if (!result.isError) setNeedsRecovery(false);
      }
    } finally {
      writing.current = false;
      setBusy(false);
    }
  };
  const checkAgain = async () => {
    if (writing.current) return;
    writing.current = true;
    setBusy(true);
    try {
      const result = await state.refresh();
      if (result && !result.isError) setNeedsRecovery(false);
      setSlot(readBrowserSubmissionAttempt(slotKey, plan));
      state.confirm.reset();
    } finally {
      writing.current = false;
      setBusy(false);
    }
  };

  return (
    <section aria-label={t("reviewTitle")} className="min-w-0 space-y-4 p-4 text-sm">
      <div className="flex items-start gap-2">
        <Lock className="mt-0.5 size-4 shrink-0" aria-hidden />
        <div className="min-w-0 space-y-1">
          <h3 className="font-medium">{t("reviewTitle")}</h3>
          <ReceiptStatus plan={plan} />
        </div>
      </div>
      <dl className="space-y-3">
        <div>
          <dt className="text-muted-foreground">{t("destination")}</dt>
          <dd className="mt-1 font-medium break-all">{origin ?? t("destinationUnavailable")}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">{t("savedCredential")}</dt>
          <dd className="mt-1">{eligible?.name ?? t("credentialUnverified")}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">{t("selectedFields")}</dt>
          <dd className="mt-1">
            {fields ? (
              <ul className="flex flex-wrap gap-1.5">
                {fields.map((field) => (
                  <li key={field} className="bg-muted rounded px-2 py-1">
                    {t(`fields.${field}`)}
                  </li>
                ))}
              </ul>
            ) : (
              t("fieldsUnavailable")
            )}
          </dd>
        </div>
        {waitingForFill && (
          <div>
            <dt className="text-muted-foreground">{t("fillDeadline")}</dt>
            <dd>
              <Deadline value={plan.expires_at} />
            </dd>
          </div>
        )}
        {filled && (
          <div>
            <dt className="text-muted-foreground">{t("submissionDeadline")}</dt>
            <dd>
              <Deadline value={plan.submission_expires_at} />
            </dd>
          </div>
        )}
      </dl>
      {(state.receipt.isError || invalidChild) && (
        <p role="alert" className="text-destructive">
          {t("receiptCheckFailed")}
        </p>
      )}
      {(waitingForFill || filled) && !eligible && (
        <p role="status" className="text-muted-foreground">
          {t("eligibilityUnavailable")}
        </p>
      )}
      {waitingForFill && (
        <>
          <p className="text-muted-foreground">{t("fillConsent")}</p>
          {!fillLive && <p role="status">{t("fillExpired")}</p>}
          <div className="flex flex-wrap gap-2">
            <Button size="sm" disabled={!canConfirm} onClick={() => void confirm(true)}>
              {t("confirmFill")}
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={!canDecline}
              onClick={() => void confirm(false)}
            >
              {t("declineFill")}
            </Button>
          </div>
        </>
      )}
      {state.confirm.isError && (
        <p role="alert" className="text-destructive">
          {t("confirmationUncertain")}
        </p>
      )}
      {filled && (
        <div className="border-border space-y-3 border-t pt-3">
          <h4 className="font-medium">{t("submissionTitle")}</h4>
          {child ? (
            <>
              <ReceiptStatus plan={child} />
              <p className="text-muted-foreground">{t("submissionConsumed")}</p>
            </>
          ) : (
            <>
              <p className="text-muted-foreground">{t("submitConsent")}</p>
              {state.submission.isPending && <p role="status">{t("checkingSubmission")}</p>}
              {(state.submission.isError || needsRecovery) && (
                <p role="status">{t("submissionRecoveryNeeded")}</p>
              )}
              {slot.attempt && (
                <p className="text-muted-foreground">{t("submissionAttemptRetained")}</p>
              )}
              {slot.unavailable && (
                <p role="alert" className="text-destructive">
                  {t("submissionStorageUnavailable")}
                </p>
              )}
              {!submitLive && <p role="status">{t("submissionExpired")}</p>}
              <Button size="sm" disabled={!canSubmit} onClick={() => void submit()}>
                {t(slot.attempt ? "retrySubmission" : "submitForm")}
              </Button>
            </>
          )}
          {state.submit.isError && !child && (
            <p role="alert" className="text-destructive">
              {t("submissionUncertain")}
            </p>
          )}
        </div>
      )}
      {state.pollingEnded && (browserCredentialPending(plan) || filled) && (
        <p role="status" className="text-muted-foreground">
          {t("pollingEnded")}
        </p>
      )}
      {(child?.state === "submitted" ||
        (plan.operation === "submit" && plan.state === "submitted")) && (
        <BrowserCredentialContinuationPanel
          source={child ?? plan}
          continuationId={continuationId}
          sourceCurrent={
            receiptCurrent &&
            (!child || (!state.submission.isError && !state.submission.isFetching))
          }
        />
      )}
      <div className="flex flex-wrap items-center gap-2">
        <Button size="sm" variant="outline" disabled={busy} onClick={() => void checkAgain()}>
          {busy ? t("checking") : t("checkAgain")}
        </Button>
        {handoff && (
          <a
            href={origin!}
            target="_blank"
            rel="noreferrer"
            className="text-primary inline-flex min-h-9 items-center gap-1.5 rounded px-2 underline underline-offset-4"
          >
            {t("openDestination")}
            <ExternalLink className="size-3.5" aria-hidden />
          </a>
        )}
      </div>
      <p className="text-muted-foreground text-xs">{t("readOnlyChecks")}</p>
      {handoff && (
        <div className="text-muted-foreground space-y-2 text-xs">
          <p>{t("separateBrowser")}</p>
          <p>{t("stopOriginatingRun")}</p>
        </div>
      )}
    </section>
  );
}
