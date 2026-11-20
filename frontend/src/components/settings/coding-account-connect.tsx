"use client";
import { cn } from "@/lib/utils";

import { NATIVE_CHOICE } from "@/components/ui/control-styles";

import { useState, useEffect, useId, type FormEvent } from "react";
import { BrandIcon } from "@/components/icons/brand-icon";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  FormField,
  Input,
} from "@/components/ui";
import { ChatGPTCallbackSteps } from "@/components/vault/chatgpt-sign-in";
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
  const common = useTranslations("common");
  const label = t(harness);
  const [credential, setCredential] = useState("");
  const [enabled, setEnabled] = useState(false);
  const [oauth, setOAuth] = useState(harness === "codex");
  const [deviceState, setDeviceState] = useState<string | null>(null);
  const pending =
    actions.connect.isPending || actions.complete.isPending || actions.start.isPending;
  const failure = (error: unknown) => toast.error(getErrorMessage(error, errors));
  const submit = async (event: FormEvent) => {
    event.preventDefault();
    try {
      if (oauth)
        await actions.complete.mutateAsync(
          deviceState !== null
            ? { label, device_state: deviceState, enabled }
            : { label, callback_url: credential.trim(), enabled },
        );
      else await actions.connect.mutateAsync({ harness, label, api_key: credential, enabled });
      setCredential("");
      actions.connect.reset();
      actions.complete.reset();
      onClose();
    } catch (error) {
      failure(error);
    }
  };
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open && !pending) onClose();
      }}
    >
      <DialogContent dismissible={!pending} className="sm:max-w-lg" data-coding-account-connect>
        <DialogHeader>
          <DialogTitle className="flex items-center gap-2">
            <BrandIcon name={harness} className="size-5" />
            {t("connectNamed", { name: t(harness) })}
          </DialogTitle>
          <DialogDescription>{t("sharing")}</DialogDescription>
        </DialogHeader>
        <form onSubmit={(event) => void submit(event)} className="space-y-4">
          {harness === "codex" && (
            <div className="flex gap-2">
              <Button
                type="button"
                variant={oauth ? "default" : "outline"}
                aria-pressed={oauth}
                disabled={pending}
                onClick={() => {
                  if (oauth) return;
                  setOAuth(true);
                  setCredential("");
                }}
              >
                {t("chatGPT")}
              </Button>
              <Button
                type="button"
                variant={oauth ? "outline" : "default"}
                aria-pressed={!oauth}
                disabled={pending}
                onClick={() => {
                  if (!oauth) return;
                  setOAuth(false);
                  setCredential("");
                  setDeviceState(null);
                }}
              >
                {t("apiKey")}
              </Button>
            </div>
          )}
          {oauth ? (
            <ChatGPTCallbackSteps
              deviceEndpoint="/coding-accounts/codex/device"
              onDeviceAuthorized={setDeviceState}
              callbackUrl={credential}
              onCallbackUrlChange={setCredential}
              startSignIn={actions.start.mutateAsync}
              starting={actions.start.isPending}
              disabled={pending}
              idPrefix={formId}
            />
          ) : (
            <FormField
              label={harness === "codex" ? t("apiKey") : t("credential")}
              htmlFor={`${formId}-credential`}
              description={t("keyHelp")}
            >
              <Input
                type="password"
                autoComplete="off"
                value={credential}
                onChange={(event) => setCredential(event.target.value)}
                required
                minLength={8}
                maxLength={8192}
                disabled={pending}
              />
            </FormField>
          )}
          <label className="flex items-start gap-2 text-sm">
            <input
              type="checkbox"
              checked={enabled}
              disabled={pending}
              onChange={(event) => setEnabled(event.target.checked)}
              className={cn(NATIVE_CHOICE, "mt-1")}
            />
            {t("consent")}
          </label>
          <DialogFooter>
            <Button type="button" variant="outline" disabled={pending} onClick={onClose}>
              {common("cancel")}
            </Button>
            <Button
              type="submit"
              disabled={pending || (!credential.trim() && !(oauth && deviceState !== null))}
            >
              {pending ? t("connecting") : t("connect")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
