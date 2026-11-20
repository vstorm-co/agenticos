"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { ExternalLink } from "lucide-react";
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Input,
  Label,
} from "@/components/ui";
import { DIALOG_COLUMN, DIALOG_FORM } from "@/lib/dialog-sizes";
import { appConnectionLabel } from "@/lib/app-connection-journey";
import type { AppConnection, ConnectedAppDefinition } from "@/types/app-connections";

export interface ConnectionAuthorizationTarget {
  app: ConnectedAppDefinition;
  connection?: AppConnection;
}

export function ConnectionAuthorizationDialog({
  target,
  busy,
  error,
  onClose,
  onContinue,
}: {
  target: ConnectionAuthorizationTarget;
  busy: boolean;
  error: string | null;
  onClose: () => void;
  onContinue: (label: string) => void;
}) {
  const t = useTranslations("appConnections");
  const [label, setLabel] = useState(target.connection?.label ?? "");
  return (
    <Dialog
      open
      onOpenChange={(open) => {
        if (!open && !busy) onClose();
      }}
    >
      <DialogContent className={`${DIALOG_FORM} ${DIALOG_COLUMN}`}>
        <DialogHeader>
          <DialogTitle>{t("connectNamed", { name: target.app.name })}</DialogTitle>
          <DialogDescription>{t("consentHint")}</DialogDescription>
        </DialogHeader>
        <div className="min-h-0 flex-1 space-y-4 overflow-y-auto">
          <p className="text-muted-foreground text-sm">{t("personalHint")}</p>
          {target.connection && <p className="text-sm">{appConnectionLabel(target.connection)}</p>}
          {!target.connection && (
            <div className="space-y-2">
              <Label htmlFor="app-connection-label">{t("accountLabel")}</Label>
              <Input
                id="app-connection-label"
                value={label}
                onChange={(event) => setLabel(event.target.value)}
                maxLength={64}
                placeholder={t("accountLabelPlaceholder")}
              />
            </div>
          )}
          <div>
            <p className="text-sm font-medium">{t("intendedAccess")}</p>
            {target.app.approval_required && <p className="text-sm">{t("approvalRequiredHint")}</p>}
            <p className="text-muted-foreground mt-1 text-sm">
              {t.has(`toolkits.${target.app.toolkit}`)
                ? t(`toolkits.${target.app.toolkit}`)
                : target.app.description}
            </p>
            <p className="text-muted-foreground mt-2 text-xs">{t("providerPermissions")}</p>
          </div>
          {error && (
            <p role="alert" className="text-destructive text-sm">
              {error}
            </p>
          )}
        </div>
        <DialogFooter>
          <Button variant="outline" disabled={busy} onClick={onClose}>
            {t("cancel")}
          </Button>
          <Button loading={busy} onClick={() => onContinue(label.trim())}>
            {t("continueToApp")}
            <ExternalLink aria-hidden />
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
