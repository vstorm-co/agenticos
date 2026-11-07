"use client";

import { useState } from "react";
import type { ConnectedAccount } from "@/types/mirage";
import { useTranslations } from "next-intl";
import {
  Button,
  Checkbox,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  Input,
  Label,
} from "@/components/ui";
import { useConnectedAccounts, type AccountOwner } from "@/hooks/use-connected-accounts";
import { DIALOG_COLUMN, DIALOG_FORM, DIALOG_BODY } from "@/lib/dialog-sizes";

export function OdooSetupDialog({
  owner,
  onClose,
  reconnectAccount,
}: {
  owner: AccountOwner;
  onClose: () => void;
  reconnectAccount?: ConnectedAccount;
}) {
  const t = useTranslations("pages.vault.connectedAccounts.setup");
  const { connectOdoo } = useConnectedAccounts(owner, { provider: "odoo" });
  const [origin, setOrigin] = useState("");
  const [database, setDatabase] = useState(reconnectAccount?.email ?? "");
  const [key, setKey] = useState("");
  const [label, setLabel] = useState(reconnectAccount?.label ?? "");
  const [write, setWrite] = useState(false);
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className={`${DIALOG_FORM} ${DIALOG_COLUMN}`}>
        <DialogHeader>
          <DialogTitle>{t("title", { provider: "Odoo" })}</DialogTitle>
          <DialogDescription>{t("odoo")}</DialogDescription>
        </DialogHeader>
        <form
          className={`${DIALOG_BODY} grid gap-3`}
          onSubmit={(event) => {
            event.preventDefault();
            connectOdoo.mutate(
              {
                credential: { origin, database, api_key: key },
                label,
                write,
                ...(reconnectAccount ? { connection_id: reconnectAccount.id } : {}),
              },
              {
                onSuccess: () => {
                  setKey("");
                  onClose();
                },
              },
            );
          }}
        >
          <div className="grid gap-2">
            <Label htmlFor="odoo-origin">{t("odooOrigin")}</Label>
            <Input
              id="odoo-origin"
              type="url"
              required
              value={origin}
              onChange={(event) => setOrigin(event.target.value)}
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="odoo-database">{t("odooDatabase")}</Label>
            <Input
              id="odoo-database"
              required
              maxLength={255}
              value={database}
              onChange={(event) => setDatabase(event.target.value)}
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="odoo-key">{t("odooKey")}</Label>
            <Input
              id="odoo-key"
              type="password"
              required
              autoComplete="new-password"
              value={key}
              onChange={(event) => setKey(event.target.value)}
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="odoo-label">{t("accountLabel")}</Label>
            <Input
              id="odoo-label"
              maxLength={64}
              value={label}
              onChange={(event) => setLabel(event.target.value)}
            />
          </div>
          <div className="flex items-center gap-2">
            <Checkbox
              id="odoo-write"
              checked={write}
              onCheckedChange={(value) => setWrite(value === true)}
            />
            <Label htmlFor="odoo-write">{t("write")}</Label>
          </div>
          <Button type="submit" disabled={connectOdoo.isPending}>
            {t("connectDirect")}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}
