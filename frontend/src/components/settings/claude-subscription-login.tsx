"use client";

import { useEffect, useId, useState } from "react";
import { ExternalLink } from "lucide-react";
import { useTranslations } from "next-intl";
import { Button, FormField, Input } from "@/components/ui";
import { claudeAuthorizationUrl } from "@/lib/personal-subscriptions-api";
import type { ClaudeSubscriptionStatus } from "@/types/personal-subscriptions";

interface LoginProps {
  status: ClaudeSubscriptionStatus;
  submitting: boolean;
  cancelling: boolean;
  restarting: boolean;
  onSubmit: (code: string) => void;
  onCancel: () => void;
  onRestart: () => void;
}

/** Mounted per login generation: replacing or leaving a sign-in clears its pasted code. */
export function ClaudeSubscriptionLogin({
  status,
  submitting,
  cancelling,
  restarting,
  onSubmit,
  onCancel,
  onRestart,
}: LoginProps) {
  const t = useTranslations("claudeSubscription");
  const id = useId();
  const [code, setCode] = useState("");
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1_000);
    return () => window.clearInterval(timer);
  }, []);
  const deadline = status.expires_at === null ? null : Date.parse(status.expires_at);
  const expired = deadline !== null && now >= deadline;
  const url = claudeAuthorizationUrl(status.authorization_url);
  const verifying = submitting || status.state === "verifying";
  const canSubmit =
    !expired &&
    !verifying &&
    !cancelling &&
    !restarting &&
    status.state === "awaiting_code" &&
    url !== null;

  return (
    <div className="space-y-3">
      {expired ? (
        <>
          <p role="status" className="text-muted-foreground text-sm">
            {t("expired")}
          </p>
          <Button
            type="button"
            size="sm"
            onClick={onRestart}
            disabled={cancelling}
            loading={restarting}
          >
            {t("startAgain")}
          </Button>
        </>
      ) : verifying ? (
        <p role="status" className="text-muted-foreground text-sm">
          {t("verifying")}
        </p>
      ) : status.state === "starting" ? (
        <p role="status" className="text-muted-foreground text-sm">
          {t("starting")}
        </p>
      ) : url === null ? (
        <p role="alert" className="text-destructive text-sm">
          {t("invalidLink")}
        </p>
      ) : (
        <form
          className="space-y-3"
          onSubmit={(event) => {
            event.preventDefault();
            if (!canSubmit || !code.trim()) return;
            const submitted = code.trim();
            setCode("");
            onSubmit(submitted);
          }}
        >
          <p className="text-muted-foreground text-sm">{t("openInstructions")}</p>
          <Button asChild size="sm" variant="outline">
            <a href={url} target="_blank" rel="noopener noreferrer" referrerPolicy="no-referrer">
              <ExternalLink className="size-3.5" aria-hidden />
              {t("openClaude")}
            </a>
          </Button>
          <FormField htmlFor={`${id}-code`} label={t("code")} description={t("codeHint")}>
            <Input
              type="password"
              autoComplete="off"
              spellCheck={false}
              maxLength={2_048}
              value={code}
              onChange={(event) => setCode(event.target.value)}
              disabled={!canSubmit}
            />
          </FormField>
          <Button type="submit" size="sm" disabled={!canSubmit || !code.trim()}>
            {t("complete")}
          </Button>
        </form>
      )}
      {!expired && deadline !== null && (
        <p className="text-muted-foreground text-xs">
          {t("expiresIn", { minutes: Math.max(1, Math.ceil((deadline - now) / 60_000)) })}
        </p>
      )}
      <Button
        type="button"
        variant="ghost"
        size="sm"
        loading={cancelling}
        disabled={restarting}
        onClick={() => {
          setCode("");
          onCancel();
        }}
      >
        {t("cancel")}
      </Button>
    </div>
  );
}
