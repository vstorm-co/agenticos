"use client";

import { useEffect, useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { useTranslations } from "next-intl";
import { Smartphone } from "lucide-react";

import { QrCode } from "@/components/mobile/qr-code";
import { SectionCard } from "@/components/settings/settings-section";
import { Button } from "@/components/ui/button";
import { createPairingCode, pairingLink, type PairingCode } from "@/lib/pairing-api";

interface Shown {
  pairing: PairingCode;
  /** When it stops working, by this browser's clock. */
  until: number;
}

/**
 * Add a phone: a QR the AgenticOS app scans to sign in as you (#2097).
 *
 * Shown only on a click, and only for a minute: whoever can see the code in that
 * minute can sign a phone in as you, the same bargain every messaging app's QR
 * sign-in makes. The countdown says how long is left; an expired code is
 * replaced by a click, never silently.
 */
export function AddPhone() {
  const t = useTranslations("mobile.addPhone");
  const [shown, setShown] = useState<Shown | null>(null);
  const [now, setNow] = useState(() => Date.now());
  const issue = useMutation({
    mutationFn: createPairingCode,
    onSuccess: (pairing) => {
      const at = Date.now();
      setNow(at);
      setShown({ pairing, until: at + pairing.expires_in * 1000 });
    },
  });

  useEffect(() => {
    if (!shown) return;
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, [shown]);

  const left = shown ? Math.max(0, Math.ceil((shown.until - now) / 1000)) : 0;
  const live = shown !== null && left > 0;

  return (
    <SectionCard title={t("title")} description={t("description")}>
      <div className="flex flex-col items-center gap-4 text-center sm:flex-row sm:items-start sm:text-left">
        <div className="bg-muted flex size-[224px] shrink-0 items-center justify-center rounded-xl">
          {live ? (
            <QrCode
              value={pairingLink(window.location.origin, shown.pairing.code)}
              label={t("qrLabel")}
            />
          ) : (
            <Smartphone className="text-muted-foreground size-10" aria-hidden />
          )}
        </div>
        <div className="space-y-3">
          <ol className="text-muted-foreground list-inside list-decimal space-y-1 text-sm">
            <li>{t("step1")}</li>
            <li>{t("step2")}</li>
            <li>{t("step3")}</li>
          </ol>
          {live ? (
            <p role="status" className="text-sm">
              {t("expiresIn", { seconds: left })}
            </p>
          ) : shown ? (
            <p role="status" className="text-sm">
              {t("expired")}
            </p>
          ) : null}
          {issue.isError ? (
            <p role="alert" className="text-destructive text-sm">
              {t("failed")}
            </p>
          ) : null}
          {live ? null : (
            <Button onClick={() => issue.mutate()} disabled={issue.isPending}>
              {shown ? t("again") : t("show")}
            </Button>
          )}
        </div>
      </div>
    </SectionCard>
  );
}
