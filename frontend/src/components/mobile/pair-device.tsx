"use client";

import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { UserRound } from "lucide-react";

import { Button, Spinner } from "@/components/ui";
import { useAdoptSession } from "@/hooks/use-auth";
import { useRouter } from "@/lib/locale-navigation";
import { previewPairingCode, redeemPairingCode, type PairingIdentity } from "@/lib/pairing-api";

/** A scanned link previews an identity; only the person's button adopts its session. */
export function PairDevice() {
  const code = useSearchParams().get("code");
  return <ConfirmPairing key={code} code={code} />;
}

function ConfirmPairing({ code }: { code: string | null }) {
  const t = useTranslations("mobile.pair");
  const router = useRouter();
  const adoptSession = useAdoptSession();
  const [identity, setIdentity] = useState<{ code: string; user: PairingIdentity } | null>(null);
  const [failed, setFailed] = useState(false);
  const [busy, setBusy] = useState(false);
  const current = useRef<string | null>(null);
  const submitting = useRef(false);

  useEffect(() => {
    current.current = code;
    if (!code) return;
    let cancelled = false;
    previewPairingCode(code).then(
      (user) => {
        if (!cancelled) setIdentity({ code, user });
      },
      () => {
        if (!cancelled) setFailed(true);
      },
    );
    return () => {
      cancelled = true;
      current.current = null;
    };
  }, [code]);

  async function confirm() {
    if (!identity || identity.code !== code || submitting.current) return;
    submitting.current = true;
    setBusy(true);
    try {
      const paired = await redeemPairingCode(identity.code);
      if (current.current !== identity.code) return;
      adoptSession(paired.user, paired.access_token);
      router.replace("/dashboard");
    } catch {
      if (current.current === identity.code) setFailed(true);
    } finally {
      if (current.current === identity.code) setBusy(false);
    }
  }

  return (
    <main className="flex min-h-dvh flex-col items-center justify-center gap-4 p-6 text-center">
      {!code || failed ? (
        <>
          <h1 className="text-lg font-semibold">{t("failed")}</h1>
          <p className="text-muted-foreground max-w-xs text-sm">{t("failedHint")}</p>
        </>
      ) : identity?.code === code ? (
        <>
          <UserRound aria-hidden className="text-muted-foreground size-8" />
          <h1 className="text-lg font-semibold">{t("confirmTitle")}</h1>
          <div className="max-w-sm break-all">
            <p className="font-medium">{identity.user.full_name}</p>
            <p>{identity.user.email}</p>
          </div>
          <p className="text-muted-foreground max-w-sm text-sm">{t("confirmHint")}</p>
          <div className="flex items-center gap-3">
            <Button variant="outline" disabled={busy} onClick={() => router.replace("/login")}>
              {t("cancel")}
            </Button>
            <Button disabled={busy} onClick={() => void confirm()}>
              {busy ? <Spinner /> : t("confirm")}
            </Button>
          </div>
        </>
      ) : (
        <>
          <Spinner />
          <p className="text-muted-foreground text-sm">{t("loading")}</p>
        </>
      )}
    </main>
  );
}
