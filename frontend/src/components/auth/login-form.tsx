"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { ArrowRight } from "lucide-react";

import { DirectoryLoginForm } from "@/components/auth/directory-login-form";
import { MfaCodeForm } from "@/components/auth/mfa-code-form";
import { OAuthBlock } from "@/components/auth/oauth-buttons";
import { goToDestination, postSignInDestination } from "@/lib/auth-landing";
import { returnToForAttempt } from "@/lib/oauth-return";
import { Button, Input, Label } from "@/components/ui";
import { useAuth, type MfaChallenge } from "@/hooks/use-auth";
import { ApiError } from "@/lib/api-client";
import { getErrorMessage, isTimeout } from "@/lib/api-error";
import { ROUTES } from "@/lib/constants";
import { registerHref } from "@/lib/invitation-links";
import { EMAIL_RE } from "@/lib/utils";

export function LoginForm() {
  const t = useTranslations("auth");
  const tErrors = useTranslations("errors");
  const search = useSearchParams();
  const router = useRouter();
  const { login, isAuthenticated, isLoading: checkingSession } = useAuth();
  // Where "create an account" goes. An invitee with no account is bounced here by
  // `AuthGuard` with the invitation in `returnTo`, and a plain link to /register
  // would drop it - leaving an `invite_only` deployment refusing somebody who is
  // holding a valid invitation (#916).
  const signUpHref = registerHref(search.toString());
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  // A sign-in that failed away from this page - a Kerberos ticket the backend
  // refused, or a browser with none to offer - lands back here with its reason.
  const [error, setError] = useState(search.get("error") ?? "");
  const [isLoading, setIsLoading] = useState(false);
  const [emailTouched, setEmailTouched] = useState(false);
  const [directory, setDirectory] = useState(false);
  // The password step passed and the sign-in is waiting on the second
  // factor: the form swaps to the code step instead of signing in.
  const [mfa, setMfa] = useState<MfaChallenge | null>(null);

  // Somebody already signed in - in this tab, or in another one the session
  // check hears about - goes on to where a sign-in would take them, not to a
  // form asking for the password again.
  useEffect(() => {
    if (checkingSession || !isAuthenticated) return;
    const returnTo = new URLSearchParams(window.location.search).get("returnTo");
    goToDestination(postSignInDestination(returnTo), (href) => router.replace(href), true);
  }, [checkingSession, isAuthenticated, router]);

  const emailValid = !email || EMAIL_RE.test(email);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);
    setError("");

    try {
      // Read off the URL at submit time: useSearchParams would demand a
      // Suspense boundary around a form that renders statically.
      const returnTo = new URLSearchParams(window.location.search).get("returnTo");
      const result = await login({ email, password }, returnTo);
      if ("mfa_required" in result) {
        setMfa(result);
        setIsLoading(false);
        return;
      }
      toast.success(t("loginSuccess"));
    } catch (err) {
      const message =
        err instanceof ApiError
          ? getErrorMessage(err, tErrors)
          : isTimeout(err)
            ? t("loginTimedOut")
            : t("loginFailedPleaseTry");
      setError(message);
      toast.error(message);
      setIsLoading(false);
    }
  };

  return (
    <div className="space-y-8">
      <div className="space-y-2">
        <span className="text-muted-foreground text-sm font-medium">{t("welcomeBack")}</span>
        <h1 className="text-foreground text-[2rem] leading-tight font-semibold tracking-tight text-balance [&_em]:not-italic">
          {t.rich("signInHeading", { em: (chunks) => <em>{chunks}</em> })}
        </h1>
        <p className="text-foreground/65 text-sm">
          {t("noAccount")}{" "}
          <Link
            href={signUpHref}
            className="text-foreground hover:text-foreground/80 font-medium underline-offset-4 hover:underline"
          >
            {t("register")}
          </Link>
        </p>
      </div>

      {mfa ? (
        <MfaCodeForm challenge={mfa} onBack={() => setMfa(null)} />
      ) : directory ? (
        <DirectoryLoginForm onBack={() => setDirectory(false)} />
      ) : (
        <form onSubmit={handleSubmit} className="space-y-5">
          <div className="space-y-1.5">
            <Label htmlFor="email" className="text-foreground text-sm font-medium">
              {t("email")}
            </Label>
            <Input
              id="email"
              type="email"
              placeholder={t("emailPlaceholder")}
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              onBlur={() => setEmailTouched(true)}
              required
              disabled={isLoading}
              autoComplete="email"
              aria-invalid={Boolean(emailTouched && email && !emailValid)}
            />
            {emailTouched && email && !emailValid && (
              <p className="text-destructive text-xs">{t("emailRequired")}</p>
            )}
          </div>

          <div className="space-y-1.5">
            <div className="flex items-center justify-between">
              <Label htmlFor="password" className="text-foreground text-sm font-medium">
                {t("password")}
              </Label>
              <Link
                href={ROUTES.FORGOT_PASSWORD}
                className="text-muted-foreground hover:text-foreground text-xs font-medium underline-offset-4 hover:underline"
              >
                {t("forgotShort")}
              </Link>
            </div>
            <Input
              id="password"
              type="password"
              placeholder="••••••••"
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              required
              disabled={isLoading}
              autoComplete="current-password"
            />
          </div>

          {error && (
            <p className="border-destructive/35 bg-destructive/[0.07] text-foreground rounded-lg border px-3 py-2 text-sm">
              {error}
            </p>
          )}

          <Button type="submit" disabled={isLoading} size="lg" className="w-full">
            {isLoading ? (
              t("loggingIn")
            ) : (
              <>
                {t("login")}
                <ArrowRight className="ml-2 h-4 w-4" />
              </>
            )}
          </Button>
        </form>
      )}

      {!directory && !mfa && (
        <OAuthBlock
          label={t("orSignInWith")}
          returnTo={returnToForAttempt(search)}
          onDirectorySignIn={() => setDirectory(true)}
        />
      )}
    </div>
  );
}
