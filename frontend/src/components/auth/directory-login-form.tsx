"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { ArrowLeft, ArrowRight } from "lucide-react";

import { usePublicConfig } from "@/components/public-config/public-config-provider";
import { MfaCodeForm } from "@/components/auth/mfa-code-form";
import { Button, Input, Label } from "@/components/ui";
import { useAuth, type MfaChallenge } from "@/hooks/use-auth";
import { ApiError } from "@/lib/api-client";
import { getErrorMessage, isTimeout } from "@/lib/api-error";
import { invitationFlowFrom } from "@/lib/invitation-links";

const LABEL = "text-foreground text-sm font-medium";

/**
 * Signing in with a company directory (LDAP) account.
 *
 * A username rather than an email address: the directory binds with the
 * account's own name, and refusing `jdoe` for not looking like an address would
 * refuse the one thing the directory accepts. The account is created on its first
 * sign-in, so an invitee's staged invitation rides along, named by the flow in
 * `returnTo` the way the provider buttons name it.
 */
export function DirectoryLoginForm({ onBack }: { onBack: () => void }) {
  const t = useTranslations("auth");
  const tErrors = useTranslations("errors");
  const { ldapDisplayName } = usePublicConfig();
  const { loginWithDirectory } = useAuth();
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  // The password step passed and the sign-in is waiting on the second
  // factor: the form swaps to the code step instead of signing in.
  const [mfa, setMfa] = useState<MfaChallenge | null>(null);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);
    setError("");
    try {
      // Read off the URL at submit time, as the password form does.
      const returnTo = new URLSearchParams(window.location.search).get("returnTo");
      const result = await loginWithDirectory(
        { username, password },
        returnTo,
        invitationFlowFrom(returnTo),
      );
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

  if (mfa) {
    return <MfaCodeForm challenge={mfa} onBack={() => setMfa(null)} />;
  }

  return (
    <form onSubmit={handleSubmit} className="space-y-5">
      <p className="text-foreground text-sm font-medium">
        {t("directorySignIn", { provider: ldapDisplayName })}
      </p>

      <div className="space-y-1.5">
        <Label htmlFor="directory-username" className={LABEL}>
          {t("directoryUsername", { provider: ldapDisplayName })}
        </Label>
        <Input
          id="directory-username"
          type="text"
          value={username}
          onChange={(e) => setUsername(e.target.value)}
          required
          disabled={isLoading}
          autoComplete="username"
          autoCapitalize="none"
          spellCheck={false}
        />
      </div>

      <div className="space-y-1.5">
        <Label htmlFor="directory-password" className={LABEL}>
          {t("password")}
        </Label>
        <Input
          id="directory-password"
          type="password"
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

      <button
        type="button"
        onClick={onBack}
        className="text-foreground/65 hover:text-foreground inline-flex items-center gap-1.5 text-sm font-medium underline-offset-4 hover:underline"
      >
        <ArrowLeft className="h-3.5 w-3.5" aria-hidden />
        {t("useEmailInstead")}
      </button>
    </form>
  );
}
