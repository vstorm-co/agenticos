"use client";

import { useTranslations } from "next-intl";

import { SecretRevealField } from "@/components/triggers/secret-reveal-field";
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui";
import { CopyableValue } from "./copyable-value";

interface WebhookSecretDialogProps {
  url: string;
  secret: string;
  onClose: () => void;
}

/**
 * A webhook's address and signing secret, straight after it is created or its
 * secret rotated - the one time the server hands the secret out.
 *
 * Says how a delivery is signed and named, because a sender that gets either
 * wrong is refused: the HMAC of the exact body in `X-Signature-256`, and an id
 * in `X-Delivery-Id` that a retry of the same delivery repeats, which is what
 * keeps a retried delivery from running the workflow twice.
 */
export function WebhookSecretDialog({ url, secret, onClose }: WebhookSecretDialogProps) {
  const t = useTranslations("pages.workflows");
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className="max-w-lg">
        <DialogHeader>
          <DialogTitle>{t("webhookReadyTitle")}</DialogTitle>
          <DialogDescription>{t("webhookReadyDescription")}</DialogDescription>
        </DialogHeader>
        <div className="space-y-4">
          <CopyableValue id="webhook-url" label={t("webhookUrl")} value={url} />
          <SecretRevealField
            id="webhook-secret"
            secret={secret}
            label={t("webhookSecret")}
            note={t("webhookSecretNote")}
          />
          <div className="bg-muted/50 space-y-1 rounded-lg border p-3 text-xs">
            <p className="font-medium">{t("webhookSigningTitle")}</p>
            <p className="text-muted-foreground">{t("webhookSigningSignature")}</p>
            <p className="text-muted-foreground">{t("webhookSigningDelivery")}</p>
          </div>
        </div>
        <DialogFooter>
          <Button onClick={onClose}>{t("webhookReadyDone")}</Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
