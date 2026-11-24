"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useConsoleRouter as useRouter } from "@/hooks/use-console-router";
import { useTranslations } from "next-intl";
import { AlertCircle, CheckCircle2, Loader2 } from "lucide-react";

import { AuthHeading } from "@/components/auth/auth-heading";
import { getErrorMessage } from "@/lib/api-error";
import { apiClient, ApiError } from "@/lib/api-client";
import { MfaCodeForm } from "@/components/auth/mfa-code-form";
import { useReauthenticate, type MfaChallenge } from "@/hooks/use-auth";
import { goToDestination, postSignInDestination } from "@/lib/auth-landing";
import { ROUTES } from "@/lib/constants";

interface MagicLinkVerified {
  mfa_required?: true;
  mfa_token?: string;
  expires_in?: number;
  return_to?: string | null;
}

/**
 * Magic-link verification page.
 *
 * Flow: user clicks the email link → arrives here with `?token=...` →
 * we POST the token to `/auth/magic-link/verify`, which signs them in via
 * the standard Set-Cookie flow → redirect to the shared post-sign-in
 * destination.
 */
export default function MagicLinkVerifyPage() {
  const tErrors = useTranslations("errors");

  const t = useTranslations("auth.magicLink");
  const recovery = useTranslations("pages.auth");
  const router = useRouter();
  const params = useSearchParams();
  const token = params.get("token");
  // A link with no token is an error before anything runs, so it is the initial
  // state rather than something an effect corrects a render later.
  const [state, setState] = useState<"verifying" | "success" | "error" | "mfa">(
    token ? "verifying" : "error",
  );
  const [error, setError] = useState<string>(token ? "" : t("errorMissingToken"));
  const [mfa, setMfa] = useState<MfaChallenge | null>(null);

  const reauthenticate = useReauthenticate();

  useEffect(() => {
    if (!token) return;
    let active = true;
    apiClient
      .post<MagicLinkVerified>("/auth/magic-link/verify", { token })
      .then(async (verified) => {
        if (!active) return;
        // A second factor on the account stops the sign-in at the challenge:
        // the page swaps to the code step, which completes it.
        if (verified?.mfa_required) {
          setMfa({
            mfa_required: true,
            mfa_token: verified.mfa_token ?? "",
            expires_in: verified.expires_in ?? 300,
            return_to: verified.return_to ?? null,
          });
          setState("mfa");
          return;
        }
        // The link may be for a different account than the tab already had.
        await reauthenticate();
        if (!active) return;
        setState("success");
        // The path travels in the token rather than in `sessionStorage`, which
        // is what the OAuth round trip uses and which is empty here: a magic
        // link is followed from an email, in another tab and often another
        // application (#1214). `postSignInDestination` still decides whether it
        // is safe to honour, and `goToDestination` picks the navigation that
        // survives a fragment - the two halves the password form and the OAuth
        // callback already share.
        goToDestination(postSignInDestination(verified?.return_to), (href) => router.replace(href));
      })
      .catch((err: unknown) => {
        if (!active) return;
        setState("error");
        setError(err instanceof ApiError ? getErrorMessage(err, tErrors) : t("errorInvalid"));
      });
    return () => {
      active = false;
    };
  }, [token, router, t, reauthenticate, tErrors]);

  return (
    <main
      id="main"
      className="bg-background flex min-h-dvh flex-col items-center justify-center px-6 py-10"
    >
      <div
        role="status"
        className="grid min-h-72 w-full max-w-md content-center gap-6 text-center wrap-anywhere"
      >
        {state === "mfa" && mfa && (
          <div className="text-left">
            <MfaCodeForm challenge={mfa} onBack={() => router.push(ROUTES.LOGIN)} />
          </div>
        )}
        {state === "verifying" && (
          <>
            <Loader2 className="text-foreground/70 mx-auto h-10 w-10 animate-spin" />
            <AuthHeading>{t("verifying")}</AuthHeading>
            <p className="text-muted-foreground text-sm">{t("verifyingHint")}</p>
          </>
        )}
        {state === "success" && (
          <>
            <CheckCircle2 className="text-brand mx-auto h-10 w-10" />
            <AuthHeading>{t("success")}</AuthHeading>
            <p className="text-muted-foreground text-sm">{t("successHint")}</p>
          </>
        )}
        {state === "error" && (
          <>
            <AlertCircle className="text-destructive mx-auto h-10 w-10" />
            <AuthHeading>{t("errorHeading")}</AuthHeading>
            <p className="text-muted-foreground text-sm">{error}</p>
            <div className="flex flex-wrap items-center justify-center gap-2 pt-2">
              <Link
                href={ROUTES.LOGIN}
                className="border-foreground/15 hover:border-foreground/40 text-foreground inline-flex h-10 items-center gap-2 rounded-full border px-4 text-sm font-medium transition-colors"
              >
                {t("signInWithPassword")}
              </Link>
              <Link
                href={ROUTES.FORGOT_PASSWORD}
                className="bg-foreground text-background hover:bg-foreground/90 inline-flex h-10 items-center gap-2 rounded-full px-4 text-sm font-medium transition-colors"
              >
                {recovery("resetPassword")}
              </Link>
            </div>
          </>
        )}
      </div>
    </main>
  );
}
