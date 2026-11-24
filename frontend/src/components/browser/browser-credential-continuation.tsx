"use client";

import { useLocale, useTranslations } from "next-intl";
import Link from "next/link";
import { Button } from "@/components/ui";
import { getPathname } from "@/lib/locale-navigation";
import { qk } from "@/lib/query-keys";
import { useBrowserCredentialAudience } from "@/hooks/use-browser-credentials";
import { useBrowserCredentialContinuation } from "@/hooks/use-browser-credential-continuation";
import {
  browserContinuationHref,
  browserContinuationPending,
  isBrowserContinuationSource,
} from "@/lib/browser-credential-continuation";
import type { BrowserCredentialPlan } from "@/types/browser-credentials";
import { BrowserContinuationConsent } from "./browser-credential-continuation-consent";
import { BrowserContinuationPrepare } from "./browser-credential-continuation-prepare";

interface ContinuationProps {
  source: BrowserCredentialPlan;
  sourceCurrent: boolean;
  continuationId?: string;
}

export function BrowserCredentialContinuationPanel(props: ContinuationProps) {
  const audience = useBrowserCredentialAudience();
  if (!isBrowserContinuationSource(props.source)) return null;
  return (
    <ContinuationPanel
      key={JSON.stringify([
        ...qk.browserContinuations.receipt(audience.actor, audience.organization, props.source),
        props.continuationId,
      ])}
      {...props}
    />
  );
}

function ContinuationPanel({ source, sourceCurrent, continuationId }: ContinuationProps) {
  const t = useTranslations("browserContinuation");
  const locale = useLocale();
  const control = useBrowserCredentialContinuation(source, sourceCurrent);
  const matches = continuationId === undefined || control.row?.id === continuationId;
  const row = matches ? control.row : undefined;
  const href = row ? browserContinuationHref(row) : null;
  const busy = control.prepare.isPending || control.confirm.isPending || control.receipt.isFetching;
  return (
    <section
      aria-label={t("title")}
      data-tour="browser-protected-continuation"
      className="border-border space-y-3 border-t pt-4"
    >
      <h4 className="font-medium">{t("title")}</h4>
      <p className="text-muted-foreground">{t("protectionPersists")}</p>
      {control.unavailable || (!control.receipt.isPending && !matches) ? (
        <p role="alert" className="text-destructive">
          {t("readUnavailable")}
        </p>
      ) : control.receipt.isPending ? (
        <p role="status">{t("checking")}</p>
      ) : row === null ? (
        <BrowserContinuationPrepare source={source} control={control} />
      ) : row ? (
        <>
          <p role="status" className="font-medium">
            {t(`states.${row.state}`)}
          </p>
          {row.reason_code && (
            <p className="text-muted-foreground">{t(`reasons.${row.reason_code}`)}</p>
          )}
          {row.state === "awaiting_confirmation" && (
            <BrowserContinuationConsent
              key={JSON.stringify([row.id, row.document_id, row.authorization_generation])}
              source={source}
              row={row}
              control={control}
            />
          )}
          {row.state === "unknown" && <p>{t("unknownOutcome")}</p>}
          {row.state === "continued" && (
            <div className="space-y-2">
              <p>{t("continuedMeaning")}</p>
              <p>{t(row.keep_signed_in ? "cookiesSaved" : "cookiesNotSaved")}</p>
              {href && (
                <Link
                  href={getPathname({ locale, href })}
                  target="_blank"
                  rel="noreferrer"
                  className="text-primary inline-flex min-h-9 items-center underline underline-offset-4"
                >
                  {t("openProtectedView")}
                </Link>
              )}
              {row.saved_sign_in_id && (
                <Link
                  href={getPathname({ locale, href: "/settings/sign-ins" })}
                  target="_blank"
                  rel="noreferrer"
                  className="text-primary block underline underline-offset-4"
                >
                  {t("manageSignIns")}
                </Link>
              )}
            </div>
          )}
        </>
      ) : null}
      {(control.needsRecovery ||
        (control.unavailable && (control.prepare.isError || control.confirm.isError))) && (
        <p role="alert">{t("writeUncertain")}</p>
      )}
      {control.pollingEnded && browserContinuationPending(row) && (
        <p role="status">{t("pollingEnded")}</p>
      )}
      <Button
        size="sm"
        variant="outline"
        disabled={!control.ready || busy}
        onClick={() => void control.refresh()}
      >
        {t("checkAgain")}
      </Button>
      <p className="text-muted-foreground text-xs">{t("checksOnlyRead")}</p>
    </section>
  );
}
