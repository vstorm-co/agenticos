"use client";

import { useState, useEffect, useId, type FormEvent } from "react";
import { BrandIcon } from "@/components/icons/brand-icon";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import {
  Button,
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  FormField,
  Input,
} from "@/components/ui";
import { getErrorMessage } from "@/lib/api-error";
import type { CodingHarness } from "@/lib/coding-accounts-api";
import type { useCodingAccounts } from "@/hooks/use-coding-accounts";

type Actions = ReturnType<typeof useCodingAccounts>;

export function CodingAccountConnect({
  harness,
  actions,
  onClose,
}: {
  harness: CodingHarness;
  actions: Actions;
  onClose: () => void;
}) {
  const resetConnect = actions.connect.reset;
  const resetComplete = actions.complete.reset;
  const resetStart = actions.start.reset;
  useEffect(
    () => () => {
      resetConnect();
      resetComplete();
      resetStart();
    },
    [resetConnect, resetComplete, resetStart],
  );
  const formId = useId();
  const t = useTranslations("codingAccounts");
  const errors = useTranslations("errors");
  const [label, setLabel] = useState("");
  const [credential, setCredential] = useState("");
  const [enabled, setEnabled] = useState(false);
  const [oauth, setOAuth] = useState(false);
  const [authorization, setAuthorization] = useState<string | null>(null);
  const pending =
    actions.connect.isPending || actions.complete.isPending || actions.start.isPending;
  const failure = (error: unknown) => toast.error(getErrorMessage(error, errors));
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    try {
      if (oauth) await actions.complete.mutateAsync({ label, callback_url: credential, enabled });
      else await actions.connect.mutateAsync({ harness, label, api_key: credential, enabled });
      setCredential("");
      actions.connect.reset();
      actions.complete.reset();
      onClose();
    } catch (error) {
      if (oauth) setAuthorization(null);
      failure(error);
    }
  };
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open) onClose();
      }}
    >
      <DialogContent className="sm:max-w-lg" data-coding-account-connect>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <BrandIcon name={harness} className="size-5" />
            {t("connectNamed", { name: t(harness) })}
          </DialogTitle>
        </DialogHeader>
        <form onSubmit={(event) => void submit(event)} className="space-y-4">
          <FormField label={t("label")} htmlFor={`${formId}-label`}>
            <Input
              value={label}
              onChange={(event) => setLabel(event.target.value)}
              maxLength={120}
              required
            />
          </FormField>
          {harness === "codex" && (
            <div className="flex gap-2">
              <Button
                type="button"
                variant={oauth ? "outline" : "default"}
                onClick={() => {
                  setOAuth(false);
                  setCredential("");
                }}
              >
                {t("apiKey")}
              </Button>
              <Button
                type="button"
                variant={oauth ? "default" : "outline"}
                onClick={() => {
                  setOAuth(true);
                  setCredential("");
                }}
              >
                {t("chatGPT")}
              </Button>
            </div>
          )}
          {oauth && (
            <div className="space-y-2 text-sm">
              <p className="text-muted-foreground">{t("oauthHelp")}</p>
              {authorization ? (
                <a href={authorization} target="_blank" rel="noreferrer" className="underline">
                  {t("continueOpenAI")}
                </a>
              ) : (
                <Button
                  type="button"
                  variant="outline"
                  disabled={pending}
                  onClick={() =>
                    void actions.start
                      .mutateAsync()
                      .then((result) => setAuthorization(result.authorization_url))
                      .catch(failure)
                  }
                >
                  {t("startSignIn")}
                </Button>
              )}
            </div>
          )}
          <FormField
            label={oauth ? t("callback") : t("credential")}
            htmlFor={`${formId}-credential`}
          >
            <Input
              type="password"
              autoComplete="off"
              value={credential}
              onChange={(event) => setCredential(event.target.value)}
              required
              minLength={oauth ? 1 : 8}
              maxLength={8192}
            />
          </FormField>
          {!oauth && <p className="text-muted-foreground text-xs">{t("keyHelp")}</p>}
          <label className="flex items-start gap-2 text-sm">
            <input
              type="checkbox"
              checked={enabled}
              onChange={(event) => setEnabled(event.target.checked)}
              className="mt-1"
            />
            {t("consent")}
          </label>
          <p className="text-muted-foreground text-xs">{t("sharing")}</p>
          <Button type="submit" disabled={pending || !label.trim() || !credential}>
            {pending ? t("connecting") : t("connect")}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}
