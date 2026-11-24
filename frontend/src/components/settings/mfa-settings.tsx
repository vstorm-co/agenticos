"use client";

import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { Check, Copy, ShieldCheck } from "lucide-react";

import { SectionCard } from "@/components/settings/settings-section";
import { Button, FormField, Input } from "@/components/ui";
import { useCopyToClipboard } from "@/hooks/use-copy-to-clipboard";
import { getErrorMessage } from "@/lib/api-error";
import { apiClient, ApiError } from "@/lib/api-client";

type Phase = "loading" | "off" | "setting-up" | "on" | "showing-codes";

async function fetchMfaStatus(): Promise<boolean> {
  const status = await apiClient.get<{ enabled: boolean }>("/auth/mfa/status");
  return status.enabled;
}

/**
 * Two-factor authentication, in Settings → Account.
 *
 * Enrolment is three steps: start setup (the secret is shown once, for the
 * authenticator app), prove it with the code the app shows, and save the
 * ten recovery codes - also shown once. Switching it off, or replacing the
 * recovery codes, takes a code from the account, so a session left open on
 * a shared screen cannot strip the factor that protects the next sign-in.
 */
export function MfaSettingsSection() {
  const t = useTranslations("pages.settings");
  const tErrors = useTranslations("errors");
  const { copy, copied } = useCopyToClipboard();
  const [phase, setPhase] = useState<Phase>("loading");
  const [setup, setSetup] = useState<{ provisioning_uri: string; secret: string } | null>(null);
  const [codes, setCodes] = useState<string[]>([]);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [failed, setFailed] = useState(false);

  const loadStatus = async () => {
    try {
      const enabled = await fetchMfaStatus();
      setFailed(false);
      setPhase(enabled ? "on" : "off");
    } catch {
      setFailed(true);
    }
  };

  useEffect(() => {
    let cancelled = false;
    void fetchMfaStatus().then(
      (enabled) => {
        if (cancelled) return;
        setFailed(false);
        setPhase(enabled ? "on" : "off");
      },
      () => {
        if (!cancelled) setFailed(true);
      },
    );
    return () => {
      cancelled = true;
    };
  }, []);

  const fail = (err: unknown) => {
    toast.error(err instanceof ApiError ? getErrorMessage(err, tErrors) : t("mfaFailed"));
  };

  const handleSetup = async () => {
    setBusy(true);
    try {
      const started = await apiClient.post<{ provisioning_uri: string; secret: string }>(
        "/auth/mfa/setup",
      );
      setSetup(started);
      setPhase("setting-up");
    } catch (err) {
      fail(err);
    } finally {
      setBusy(false);
    }
  };

  const handleEnable = async () => {
    setBusy(true);
    try {
      const answer = await apiClient.post<{ recovery_codes: string[] }>("/auth/mfa/enable", {
        code,
      });
      setCodes(answer.recovery_codes);
      setCode("");
      setPhase("showing-codes");
    } catch (err) {
      fail(err);
    } finally {
      setBusy(false);
    }
  };

  const handleDisable = async () => {
    setBusy(true);
    try {
      await apiClient.post("/auth/mfa/disable", { code });
      setCode("");
      setPhase("off");
      toast.success(t("mfaOff"));
    } catch (err) {
      fail(err);
    } finally {
      setBusy(false);
    }
  };

  const handleRegenerate = async () => {
    setBusy(true);
    try {
      const answer = await apiClient.post<{ recovery_codes: string[] }>(
        "/auth/mfa/recovery-codes",
        { code },
      );
      setCodes(answer.recovery_codes);
      setCode("");
      setPhase("showing-codes");
    } catch (err) {
      fail(err);
    } finally {
      setBusy(false);
    }
  };

  const codesDone = async () => {
    setCodes([]);
    setSetup(null);
    await loadStatus();
  };

  return (
    <SectionCard icon={ShieldCheck} title={t("mfaTitle")} description={t("mfaDescription")}>
      {failed ? (
        <div className="space-y-3">
          <p className="text-foreground text-sm">{t("mfaFailed")}</p>
          <Button variant="outline" size="sm" onClick={() => void loadStatus()}>
            {t("mfaRetry")}
          </Button>
        </div>
      ) : phase === "loading" ? (
        <p className="text-muted-foreground text-sm">…</p>
      ) : phase === "showing-codes" ? (
        <div className="space-y-4">
          <p className="text-foreground text-sm font-semibold">{t("mfaRecoveryTitle")}</p>
          <p className="text-muted-foreground text-xs leading-relaxed">{t("mfaRecoveryHint")}</p>
          <ul className="grid grid-cols-2 gap-2">
            {codes.map((recovery) => (
              <li
                key={recovery}
                className="bg-muted rounded-lg px-3 py-2 font-mono text-sm tracking-wider"
              >
                {recovery}
              </li>
            ))}
          </ul>
          <div className="flex flex-wrap gap-2">
            <Button variant="outline" size="sm" onClick={() => void copy(codes.join("\n"))}>
              {copied ? (
                <>
                  <Check className="mr-2 h-3.5 w-3.5" />
                  {t("mfaCopied")}
                </>
              ) : (
                <>
                  <Copy className="mr-2 h-3.5 w-3.5" />
                  {t("mfaCopy")}
                </>
              )}
            </Button>
            <Button size="sm" onClick={() => void codesDone()}>
              {t("mfaCodesSaved")}
            </Button>
          </div>
        </div>
      ) : phase === "setting-up" && setup ? (
        <div className="space-y-4">
          <p className="text-muted-foreground text-sm leading-relaxed">{t("mfaSetupHint")}</p>
          <FormField label={t("mfaSecret")} htmlFor="mfa-secret">
            <div className="flex gap-2">
              <Input
                id="mfa-secret"
                readOnly
                value={setup.secret}
                className="font-mono tracking-wider"
              />
              <Button variant="outline" size="sm" onClick={() => void copy(setup.secret)}>
                {copied ? <Check className="h-3.5 w-3.5" /> : <Copy className="h-3.5 w-3.5" />}
              </Button>
            </div>
          </FormField>
          <form
            className="space-y-4"
            onSubmit={(event) => {
              event.preventDefault();
              void handleEnable();
            }}
          >
            <FormField label={t("mfaCodeLabel")} htmlFor="mfa-enable-code">
              <Input
                id="mfa-enable-code"
                value={code}
                onChange={(e) => setCode(e.target.value)}
                autoComplete="one-time-code"
                maxLength={9}
                className="tracking-[0.2em]"
              />
            </FormField>
            <div className="flex flex-wrap gap-2">
              <Button type="submit" loading={busy} disabled={busy || code.trim().length < 6}>
                {t("mfaEnable")}
              </Button>
              <Button
                type="button"
                variant="outline"
                onClick={() => {
                  setSetup(null);
                  setPhase("off");
                }}
              >
                {t("mfaBack")}
              </Button>
            </div>
          </form>
        </div>
      ) : phase === "on" ? (
        <div className="space-y-4">
          <p className="text-foreground text-sm leading-relaxed">{t("mfaEnabled")}</p>
          <form
            className="space-y-4"
            onSubmit={(event) => {
              event.preventDefault();
              void handleDisable();
            }}
          >
            <FormField label={t("mfaCodeLabel")} htmlFor="mfa-disable-code">
              <Input
                id="mfa-disable-code"
                value={code}
                onChange={(e) => setCode(e.target.value)}
                autoComplete="one-time-code"
                maxLength={9}
                className="tracking-[0.2em]"
              />
            </FormField>
            <p className="text-muted-foreground text-xs leading-relaxed">{t("mfaDisableHint")}</p>
            <div className="flex flex-wrap gap-2">
              <Button
                type="submit"
                variant="outline"
                loading={busy}
                disabled={busy || code.trim().length < 6}
              >
                {t("mfaDisable")}
              </Button>
              <Button
                type="button"
                variant="outline"
                loading={busy}
                disabled={busy || code.trim().length < 6}
                onClick={() => void handleRegenerate()}
              >
                {t("mfaRegenerate")}
              </Button>
            </div>
            <p className="text-muted-foreground text-xs leading-relaxed">
              {t("mfaRegenerateHint")}
            </p>
          </form>
        </div>
      ) : (
        <div className="space-y-4">
          <p className="text-foreground text-sm leading-relaxed">{t("mfaOff")}</p>
          <Button loading={busy} disabled={busy} onClick={() => void handleSetup()}>
            {t("mfaSetup")}
          </Button>
        </div>
      )}
    </SectionCard>
  );
}
