"use client";

import { useEffect, useId, useState } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useConsoleRouter as useRouter } from "@/hooks/use-console-router";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { ArrowRight } from "lucide-react";

import { DirectoryLoginForm } from "@/components/auth/directory-login-form";
import { OAuthBlock } from "@/components/auth/oauth-buttons";
import { goToDestination, postSignInDestination } from "@/lib/auth-landing";
import { returnToForAttempt } from "@/lib/oauth-return";
import { useBranding } from "@/components/branding/branding-provider";
import { ProviderSignIn } from "@/components/auth/provider-sign-in";
import { AuthHeading } from "@/components/auth/auth-heading";
import { Button, Input, Label } from "@/components/ui";
import { useAuth } from "@/hooks";
import { ApiError } from "@/lib/api-client";
import { credentialsRejected, getErrorMessage, isTimeout } from "@/lib/api-error";
import { ROUTES } from "@/lib/constants";
import { registerHref } from "@/lib/invitation-links";
import { EMAIL_RE } from "@/lib/utils";
import { useRejectedFieldMotion } from "@/hooks/use-rejected-field-motion";

export function LoginForm() {
  const branding = useBranding();
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
  const [rejectedAttempts, setRejectedAttempts] = useState(0);
  const passwordRef = useRejectedFieldMotion(rejectedAttempts);
  const errorId = useId();
  const emailErrorId = useId();

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
      await login({ email, password }, returnTo);
      toast.success(t("loginSuccess"));
    } catch (err) {
      if (credentialsRejected(err)) setRejectedAttempts((count) => count + 1);
      else setRejectedAttempts(0);
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

  if (!branding.passwordSignInEnabled) return <ProviderSignIn error={error} />;

  return (
    <div className="space-y-8">
      <div className="space-y-2">
        <AuthHeading>{t("signInHeading")}</AuthHeading>
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

      {directory ? (
        <DirectoryLoginForm onBack={() => setDirectory(false)} />
      ) : (
        <form onSubmit={handleSubmit} className="space-y-5">
          <div className="space-y-1.5">
            <Label htmlFor="email" className="text-foreground text-sm font-medium">
              {t("email")}
            </Label>
            <Input
              id="email"
              name="email"
              type="email"
              placeholder={t("emailPlaceholder")}
              value={email}
              onChange={(e) => {
                setEmail(e.target.value);
                setRejectedAttempts(0);
              }}
              spellCheck={false}
              onBlur={() => setEmailTouched(true)}
              required
              disabled={isLoading}
              autoComplete="email"
              aria-invalid={Boolean(emailTouched && email && !emailValid)}
              aria-describedby={emailTouched && email && !emailValid ? emailErrorId : undefined}
            />
            {emailTouched && email && !emailValid && (
              <p id={emailErrorId} className="text-destructive-ink text-xs">
                {t("pleaseEnterValidEmail")}
              </p>
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
              name="password"
              ref={passwordRef}
              type="password"
              placeholder="••••••••"
              value={password}
              onChange={(e) => {
                setPassword(e.target.value);
                setRejectedAttempts(0);
              }}
              aria-invalid={rejectedAttempts > 0 && Boolean(error)}
              aria-describedby={error ? errorId : undefined}
              required
              disabled={isLoading}
              autoComplete="current-password"
            />
          </div>

          {error && (
            <p
              id={errorId}
              role="alert"
              className="border-destructive/35 bg-destructive/[0.07] text-foreground rounded-lg border px-3 py-2 text-sm"
            >
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

      {!directory && (
        <OAuthBlock
          label={t("orSignInWith")}
          returnTo={returnToForAttempt(search)}
          onDirectorySignIn={() => setDirectory(true)}
        />
      )}
    </div>
  );
}
