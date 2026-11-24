"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { ArrowLeft, ArrowRight } from "lucide-react";

import { Button, Input, Label } from "@/components/ui";
import { useAuth, type MfaChallenge } from "@/hooks/use-auth";
import { ApiError } from "@/lib/api-client";
import { getErrorMessage, isTimeout } from "@/lib/api-error";

/**
 * The second step of a sign-in: the authenticator code, or a recovery code.
 *
 * Shown when the password step answered with a challenge instead of a
 * session. Completing it signs in through the same path the password did,
 * so a challenge that arrived by magic link still lands where the link was
 * headed. The challenge itself is short-lived - five minutes - and a wrong
 * code is refused the way a wrong password is.
 */
export function MfaCodeForm({
  challenge,
  onBack,
}: {
  challenge: MfaChallenge;
  onBack: () => void;
}) {
  const t = useTranslations("auth");
  const tErrors = useTranslations("errors");
  const { verifyMfa } = useAuth();
  const [code, setCode] = useState("");
  const [error, setError] = useState("");
  const [isLoading, setIsLoading] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setIsLoading(true);
    setError("");

    try {
      await verifyMfa(challenge.mfa_token, code, challenge.return_to ?? null);
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
    <form onSubmit={handleSubmit} className="space-y-5">
      <p className="text-foreground text-sm">{t("mfaPrompt")}</p>

      <div className="space-y-1.5">
        <Label htmlFor="mfa-code" className="text-foreground text-sm font-medium">
          {t("mfaCode")}
        </Label>
        <Input
          id="mfa-code"
          type="text"
          value={code}
          onChange={(e) => setCode(e.target.value)}
          required
          disabled={isLoading}
          autoComplete="one-time-code"
          autoCapitalize="characters"
          spellCheck={false}
          maxLength={9}
          placeholder={t("mfaCodePlaceholder")}
          className="h-11 rounded-lg text-base tracking-[0.2em] md:text-[15px]"
        />
        <p className="text-muted-foreground text-xs">{t("mfaCodeHint")}</p>
      </div>

      {error && (
        <p className="border-destructive/35 bg-destructive/[0.07] text-foreground rounded-lg border px-3 py-2 text-sm">
          {error}
        </p>
      )}

      <Button
        type="submit"
        className="h-11 w-full rounded-lg text-[15px] font-semibold"
        disabled={isLoading || code.trim().length < 6}
      >
        {isLoading ? t("loggingIn") : t("mfaVerify")}
        <ArrowRight className="size-4" />
      </Button>

      <button
        type="button"
        onClick={onBack}
        disabled={isLoading}
        className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1.5 text-sm font-medium transition-colors"
      >
        <ArrowLeft className="size-4" />
        {t("mfaBack")}
      </button>
    </form>
  );
}
