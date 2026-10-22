"use client";

import { useEffect, useState } from "react";
import { useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";

import { Spinner } from "@/components/ui";
import { useAdoptSession } from "@/hooks/use-auth";
import { useRouter } from "@/lib/locale-navigation";
import { redeemPairingCode, type Paired } from "@/lib/pairing-api";

// A single-use code must be POSTed exactly once; a remount - Strict Mode, a
// re-render of the page - shares the request rather than spending the code twice.
const redemptions = new Map<string, Promise<Paired>>();

function redeemOnce(code: string): Promise<Paired> {
  let pending = redemptions.get(code);
  if (pending === undefined) {
    pending = redeemPairingCode(code).finally(() => redemptions.delete(code));
    redemptions.set(code, pending);
  }
  return pending;
}

/**
 * The phone signing in with the code it scanned: redeem it, adopt the session,
 * open the console. A spent or expired code says so and points back to the
 * console that showed it, where a new one is a click away.
 */
export function PairDevice() {
  const t = useTranslations("mobile.pair");
  const router = useRouter();
  const adoptSession = useAdoptSession();
  const code = useSearchParams().get("code");
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!code) return;
    let cancelled = false;
    redeemOnce(code)
      .then((paired) => {
        if (cancelled) return;
        adoptSession(paired.user, paired.access_token);
        router.replace("/dashboard");
      })
      .catch(() => {
        if (!cancelled) setFailed(true);
      });
    return () => {
      cancelled = true;
    };
  }, [adoptSession, code, router]);

  return (
    <main className="flex min-h-dvh flex-col items-center justify-center gap-3 p-6 text-center">
      {!code || failed ? (
        <>
          <h1 className="text-lg font-semibold">{t("failed")}</h1>
          <p className="text-muted-foreground max-w-xs text-sm">{t("failedHint")}</p>
        </>
      ) : (
        <>
          <Spinner />
          <p className="text-muted-foreground text-sm">{t("signingIn")}</p>
        </>
      )}
    </main>
  );
}
