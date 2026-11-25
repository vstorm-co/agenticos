"use client";

import { useState } from "react";
import { useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";

import { AuthHeading } from "@/components/auth/auth-heading";
import { DirectoryLoginForm } from "@/components/auth/directory-login-form";
import { OAuthBlock, useSignInProviders } from "@/components/auth/oauth-buttons";
import { returnToForAttempt } from "@/lib/oauth-return";

export function ProviderSignIn({ error }: { error?: string }) {
  const t = useTranslations("auth");
  const search = useSearchParams();
  const signInProviders = useSignInProviders();
  const [directory, setDirectory] = useState(false);
  return (
    <div className="space-y-8">
      <div className="space-y-2">
        <AuthHeading>{t("signInHeading")}</AuthHeading>
        <p className="text-foreground/65 text-sm">
          {signInProviders.length ? t("providerSignInOnly") : t("providerSignInUnavailable")}
        </p>
      </div>
      {error && (
        <p role="alert" className="text-destructive-ink text-sm">
          {error}
        </p>
      )}
      {directory ? (
        <DirectoryLoginForm
          onBack={() => setDirectory(false)}
          backLabel={t("chooseSignInMethod")}
        />
      ) : (
        <OAuthBlock
          label={t("orSignInWith")}
          divider={false}
          returnTo={returnToForAttempt(search)}
          onDirectorySignIn={() => setDirectory(true)}
        />
      )}
    </div>
  );
}
