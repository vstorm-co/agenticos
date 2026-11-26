"use client";

import { useState } from "react";
import { Copy, KeyRound, Mail } from "lucide-react";
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
  Input,
} from "@/components/ui";
import { getErrorMessage } from "@/lib/api-error";
import { apiClient } from "@/lib/api-client";
import { DIALOG_FORM } from "@/lib/dialog-sizes";
import type { AdminUser } from "@/types";

export function UserPasswordReset({ user, onClose }: { user: AdminUser; onClose: () => void }) {
  const t = useTranslations("admin");
  const tErrors = useTranslations("errors");
  const [link, setLink] = useState<string | null>(null);
  const [pending, setPending] = useState<"email" | "link" | null>(null);
  const [error, setError] = useState<string | null>(null);

  const copy = async (url: string) => {
    try {
      await navigator.clipboard.writeText(url);
      toast.success(t("passwordResetLinkCopied"));
    } catch {
      toast.error(t("copyFailed"));
    }
  };

  const issue = async (delivery: "email" | "link") => {
    if (pending) return;
    setPending(delivery);
    setError(null);
    try {
      const result = await apiClient.post<{ reset_url: string | null }>(
        `/admin/users/${user.id}/password-reset`,
        { delivery },
      );
      if (delivery === "email") {
        toast.success(t("passwordResetEmailSent"));
        onClose();
      } else if (result.reset_url) {
        setLink(result.reset_url);
        await copy(result.reset_url);
      } else {
        setError(t("passwordResetFailed"));
      }
    } catch (cause) {
      setError(getErrorMessage(cause, tErrors, t("passwordResetFailed")));
    } finally {
      setPending(null);
    }
  };

  return (
    <Dialog open onOpenChange={(open) => !open && !pending && onClose()}>
      <DialogContent className={DIALOG_FORM} dismissible={!pending}>
        <DialogHeader>
          <DialogTitle>{t("passwordReset")}</DialogTitle>
          <DialogDescription>{t("passwordResetHint", { email: user.email })}</DialogDescription>
        </DialogHeader>
        {link && (
          <div className="flex min-w-0 items-center gap-2">
            <Input
              value={link}
              readOnly
              aria-label={t("passwordResetLink")}
              onFocus={(event) => event.currentTarget.select()}
            />
            <Button
              type="button"
              variant="outline"
              size="icon"
              onClick={() => void copy(link)}
              aria-label={t("copyPasswordResetLink")}
            >
              <Copy aria-hidden />
            </Button>
          </div>
        )}
        {error && (
          <p role="alert" className="text-destructive text-sm">
            {error}
          </p>
        )}
        <DialogFooter className="flex-wrap">
          {link ? (
            <Button onClick={onClose}>{t("close")}</Button>
          ) : (
            <>
              <Button
                variant="outline"
                onClick={() => void issue("link")}
                disabled={pending !== null}
                loading={pending === "link"}
              >
                <KeyRound aria-hidden />
                {t("copyPasswordResetLink")}
              </Button>
              <Button
                onClick={() => void issue("email")}
                disabled={pending !== null}
                loading={pending === "email"}
              >
                <Mail aria-hidden />
                {t("sendPasswordResetEmail")}
              </Button>
            </>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
