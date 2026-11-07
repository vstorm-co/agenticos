"use client";

import { DIALOG_COLUMN, DIALOG_FORM, DIALOG_BODY } from "@/lib/dialog-sizes";
import { useState } from "react";
import type { ConnectedAccount } from "@/types/mirage";
import { useTranslations } from "next-intl";
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  Input,
  Label,
} from "@/components/ui";
import { useConnectedAccounts, type AccountOwner } from "@/hooks/use-connected-accounts";

export function ImapSetupDialog({
  owner,
  onClose,
  reconnectAccount,
}: {
  owner: AccountOwner;
  onClose: () => void;
  reconnectAccount?: ConnectedAccount;
}) {
  const t = useTranslations("pages.vault.connectedAccounts.setup");
  const { connectImap } = useConnectedAccounts(owner, { provider: "imap" });
  const [host, setHost] = useState("");
  const [port, setPort] = useState(993);
  const [username, setUsername] = useState(reconnectAccount?.email ?? "");
  const [password, setPassword] = useState("");
  const [folder, setFolder] = useState("INBOX");
  const [label, setLabel] = useState(reconnectAccount?.label ?? "");
  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className={`${DIALOG_FORM} ${DIALOG_COLUMN}`}>
        <DialogHeader>
          <DialogTitle>{t("title", { provider: "IMAP" })}</DialogTitle>
          <DialogDescription>{t("imap")}</DialogDescription>
        </DialogHeader>
        <form
          className={`${DIALOG_BODY} grid gap-3`}
          onSubmit={(event) => {
            event.preventDefault();
            connectImap.mutate(
              {
                credential: { host, port, username, password, folder },
                label,
                ...(reconnectAccount ? { connection_id: reconnectAccount.id } : {}),
              },
              {
                onSuccess: () => {
                  setPassword("");
                  onClose();
                },
              },
            );
          }}
        >
          <div className="grid gap-2">
            <Label htmlFor="imap-host">{t("host")}</Label>
            <Input
              id="imap-host"
              required
              value={host}
              onChange={(event) => setHost(event.target.value)}
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="imap-port">{t("port")}</Label>
            <Input
              id="imap-port"
              type="number"
              min={1}
              max={65535}
              required
              value={port}
              onChange={(event) => setPort(Number(event.target.value))}
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="imap-user">{t("username")}</Label>
            <Input
              id="imap-user"
              required
              value={username}
              onChange={(event) => setUsername(event.target.value)}
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="imap-password">{t("password")}</Label>
            <Input
              id="imap-password"
              type="password"
              autoComplete="new-password"
              required
              value={password}
              onChange={(event) => setPassword(event.target.value)}
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="imap-folder">{t("folder")}</Label>
            <Input
              id="imap-folder"
              required
              value={folder}
              onChange={(event) => setFolder(event.target.value)}
            />
          </div>
          <div className="grid gap-2">
            <Label htmlFor="imap-label">{t("accountLabel")}</Label>
            <Input
              id="imap-label"
              value={label}
              onChange={(event) => setLabel(event.target.value)}
            />
          </div>
          <Button type="submit" disabled={connectImap.isPending || !host || !username || !password}>
            {t("connectDirect")}
          </Button>
        </form>
      </DialogContent>
    </Dialog>
  );
}
