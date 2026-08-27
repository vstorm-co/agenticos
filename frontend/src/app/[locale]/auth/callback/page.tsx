"use client";

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { Spinner } from "@/components/ui";
import { apiClient } from "@/lib/api-client";
import { useAdoptSession } from "@/hooks/use-auth";
import { postSignInDestination } from "@/lib/auth-landing";
import { takeReturnTo } from "@/lib/oauth-return";
import type { User } from "@/types";
import { useTranslations } from "next-intl";

type Adopted = { user: User; access_token: string };

// A single-use code must be POSTed exactly once. React Strict Mode mounts this
// effect, cleans it up, and mounts it again in development, and a plain remount
// does the same: without sharing the request the second POST sends the code the
// first already spent and gets a 401, failing a sign-in that worked. Keyed by
// code and held outside the component so it survives the remount; cleared when
// the request settles.
const exchanges = new Map<string, Promise<Adopted>>();

function exchangeCode(code: string): Promise<Adopted> {
  let pending = exchanges.get(code);
  if (pending === undefined) {
    pending = apiClient
      .post<Adopted>("/auth/oauth-callback", { code })
      .finally(() => exchanges.delete(code));
    exchanges.set(code, pending);
  }
  return pending;
}

export default function AuthCallbackPage() {
  const t = useTranslations("pages.root");
  const router = useRouter();
  const searchParams = useSearchParams();
  // Two sources, one derived value. What the provider sent is already in the
  // URL and needs no state at all; the exchange failing later does, but only as
  // a flag - keeping the message here means neither is written from an effect
  // synchronously, and the URL case is shown a render earlier than it was.
  const [exchangeFailed, setExchangeFailed] = useState(false);
  // i18n-exempt: a sentinel nothing renders - what the branch below shows is
  // `t("signInFailedRedirecting")`, and the provider's own code is discarded the same way.
  const error = searchParams.get("error") ?? (exchangeFailed ? "Sign-in failed" : null);

  const adoptSession = useAdoptSession();

  useEffect(() => {
    const code = searchParams.get("code");
    const errParam = searchParams.get("error");

    if (errParam) {
      const t = setTimeout(
        () => router.replace(`/login?error=${encodeURIComponent(errParam)}`),
        1500,
      );
      return () => clearTimeout(t);
    }
    if (!code) {
      router.replace("/login?error=missing_code");
      return;
    }

    let cancelled = false;
    (async () => {
      try {
        const data = await exchangeCode(code);
        if (cancelled) return;
        adoptSession(data.user, data.access_token);
        // The deep link the visitor was headed to, written beside the provider
        // link they clicked and consumed here. Not the OAuth `state` parameter:
        // the trip starts and ends in the same tab on this origin (#135).
        router.replace(postSignInDestination(takeReturnTo()));
      } catch {
        if (!cancelled) {
          setExchangeFailed(true);
          router.replace("/login?error=oauth_failed");
        }
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [router, searchParams, adoptSession]);

  return (
    <div className="flex min-h-[50vh] items-center justify-center">
      {error ? (
        <p className="text-foreground/65 text-sm">{t("signInFailedRedirecting")}</p>
      ) : (
        // A token exchange and a redirect. There is no layout to promise here,
        // so this is a spinner rather than a skeleton of a page nobody stays on.
        <p className="text-foreground/65 flex items-center gap-3 text-sm">
          <Spinner className="h-4 w-4" aria-hidden />
          {t("completingSignIn")}
        </p>
      )}
    </div>
  );
}
