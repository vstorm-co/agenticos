"use client";

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";

import { Spinner } from "@/components/ui";
import { apiClient } from "@/lib/api-client";
import { useAdoptSession } from "@/hooks/use-auth";
import { postSignInDestination } from "@/lib/auth-landing";
import type { User } from "@/types";
import { useTranslations } from "next-intl";

export default function AuthCallbackPage() {
  const t = useTranslations("pages.root");
  const router = useRouter();
  const searchParams = useSearchParams();
  // Two sources, one derived value. What the provider sent is already in the
  // URL and needs no state at all; the exchange failing later does, but only as
  // a flag - keeping the message here means neither is written from an effect
  // synchronously, and the URL case is shown a render earlier than it was.
  const [exchangeFailed, setExchangeFailed] = useState(false);
  const error = searchParams.get("error") ?? (exchangeFailed ? "Sign-in failed" : null);

  const adoptSession = useAdoptSession();

  useEffect(() => {
    const accessToken = searchParams.get("access_token");
    const refreshToken = searchParams.get("refresh_token");
    const errParam = searchParams.get("error");

    if (errParam) {
      const t = setTimeout(
        () => router.replace(`/login?error=${encodeURIComponent(errParam)}`),
        1500,
      );
      return () => clearTimeout(t);
    }
    if (!accessToken || !refreshToken) {
      router.replace("/login?error=missing_tokens");
      return;
    }

    let cancelled = false;
    (async () => {
      try {
        const data = await apiClient.post<{ user: User; access_token: string }>(
          "/auth/oauth-callback",
          { access_token: accessToken, refresh_token: refreshToken },
        );
        if (cancelled) return;
        adoptSession(data.user, data.access_token);
        // No deep link here: carrying one through the provider round trip
        // needs the OAuth `state` parameter, which this flow does not use yet.
        router.replace(postSignInDestination());
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
          Completing sign-in…
        </p>
      )}
    </div>
  );
}
