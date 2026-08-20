"use client";

import Link from "next/link";
import { Lock } from "lucide-react";
import { useTranslations } from "next-intl";

import { useBranding } from "@/components/branding/branding-provider";
import { ROUTES } from "@/lib/constants";

/**
 * What stands where the sign-up form was, on a deployment that has closed it.
 *
 * A page rather than a disabled button: the form is not going to work, and an
 * input somebody can fill in for a request that will always be refused is worse
 * than no input. The way back to sign-in stays, because the most likely visitor
 * here is somebody who already has an account.
 */
export function SignupClosed() {
  const t = useTranslations("auth");
  const { appName } = useBranding();

  return (
    <div className="space-y-6">
      <span className="bg-muted text-foreground inline-flex h-11 w-11 items-center justify-center rounded-xl">
        <Lock className="h-5 w-5" aria-hidden />
      </span>
      <div className="space-y-2">
        <h1 className="text-display-md text-foreground">{t("signupClosedHeading")}</h1>
        <p className="text-foreground/65 text-sm">{t("signupClosedBody", { app: appName })}</p>
      </div>
      <Link
        href={ROUTES.LOGIN}
        className="text-foreground hover:text-foreground/80 text-sm font-medium underline-offset-4 hover:underline"
      >
        {t("login")}
      </Link>
    </div>
  );
}
