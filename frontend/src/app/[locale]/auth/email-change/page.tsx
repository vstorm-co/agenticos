"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { AlertCircle, CheckCircle2, Loader2 } from "lucide-react";

import { getErrorMessage } from "@/lib/api-error";
import { apiClient, ApiError } from "@/lib/api-client";
import { ROUTES } from "@/lib/constants";

/**
 * Confirming an address a change was requested for.
 *
 * Followed from the *new* address, which is routinely a different browser from
 * the one that asked for the change - so this page signs nobody in and needs no
 * session. The token is the whole of the proof, and the account keeps using its
 * previous address until this call succeeds (#1772).
 *
 * The same shape as the magic-link landing beside it, minus the sign-in: there
 * is no destination to return to, because whoever follows this link may not be
 * signed in anywhere.
 */
export default function EmailChangeConfirmPage() {
  const t = useTranslations("auth.emailChange");
  const tErrors = useTranslations("errors");
  const params = useSearchParams();
  const token = params.get("token");
  // A link with no token is an error before anything runs, so it is the initial
  // state rather than something an effect corrects a render later.
  const [state, setState] = useState<"confirming" | "success" | "error">(
    token ? "confirming" : "error",
  );
  const [error, setError] = useState<string>(token ? "" : t("errorMissingToken"));

  useEffect(() => {
    if (!token) return;
    let active = true;
    apiClient
      .post("/auth/email-change/confirm", { token })
      .then(() => {
        if (!active) return;
        setState("success");
      })
      .catch((err: unknown) => {
        if (!active) return;
        setState("error");
        setError(err instanceof ApiError ? getErrorMessage(err, tErrors) : t("errorInvalid"));
      });
    return () => {
      active = false;
    };
  }, [token, t, tErrors]);

  return (
    <main
      id="main"
      className="bg-background flex min-h-screen flex-col items-center justify-center px-6"
    >
      <div className="w-full max-w-md space-y-6 text-center">
        {state === "confirming" && (
          <>
            <Loader2 className="text-foreground/70 mx-auto h-10 w-10 animate-spin" />
            <h1 className="text-foreground text-2xl font-bold tracking-tight">{t("confirming")}</h1>
          </>
        )}
        {state === "success" && (
          <>
            <CheckCircle2 className="text-brand mx-auto h-10 w-10" />
            <h1 className="text-foreground text-2xl font-bold tracking-tight">{t("success")}</h1>
            <p className="text-foreground/65 text-sm">{t("successHint")}</p>
          </>
        )}
        {state === "error" && (
          <>
            <AlertCircle className="text-destructive mx-auto h-10 w-10" />
            <h1 className="text-foreground text-2xl font-bold tracking-tight">
              {t("errorHeading")}
            </h1>
            <p className="text-foreground/65 text-sm">{error}</p>
          </>
        )}
        <div className="flex flex-wrap items-center justify-center gap-2 pt-2">
          <Link
            href={ROUTES.LOGIN}
            className="border-foreground/15 hover:border-foreground/40 text-foreground inline-flex h-10 items-center gap-2 rounded-full border px-4 text-sm font-medium transition-colors"
          >
            {t("signIn")}
          </Link>
        </div>
      </div>
    </main>
  );
}
