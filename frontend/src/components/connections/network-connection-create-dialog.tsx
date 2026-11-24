"use client";

import { useState, type FormEvent } from "react";
import { useTranslations } from "next-intl";

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
import { getErrorMessage } from "@/lib/api-error";
import type { NetworkConnectionScope } from "@/types/network-connections";

export function NetworkConnectionCreateDialog({
  open,
  onOpenChange,
  available,
  scopes,
  saving,
  onCreate,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  available: boolean | null;
  scopes: { user: boolean; org: boolean };
  saving: boolean;
  onCreate: (input: { name: string; scope: NetworkConnectionScope }) => Promise<void>;
}) {
  const t = useTranslations("networkConnections");
  const tErrors = useTranslations("errors");
  const [name, setName] = useState("");
  const [scope, setScope] = useState<NetworkConnectionScope>(scopes.user ? "user" : "org");
  const [error, setError] = useState<string | null>(null);
  const selectedScope = scopes[scope] ? scope : scopes.user ? "user" : "org";

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const trimmed = name.trim();
    if (!trimmed || !scopes[selectedScope]) return;
    setError(null);
    try {
      await onCreate({ name: trimmed, scope: selectedScope });
      setName("");
      onOpenChange(false);
    } catch (caught) {
      setError(getErrorMessage(caught, tErrors));
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>{t("create.title")}</DialogTitle>
          <DialogDescription>{t("create.description")}</DialogDescription>
        </DialogHeader>
        <form className="space-y-4" onSubmit={(event) => void submit(event)}>
          <div className="space-y-2">
            <Label htmlFor="network-connection-name">{t("create.nameLabel")}</Label>
            <Input
              id="network-connection-name"
              data-tour="tailscale-name"
              value={name}
              onChange={(event) => setName(event.target.value)}
              maxLength={120}
              required
            />
          </div>
          {(scopes.user || scopes.org) && (
            <div className="space-y-2">
              <Label htmlFor="network-connection-scope">{t("create.scopeLabel")}</Label>
              <select
                id="network-connection-scope"
                data-tour="tailscale-scope"
                className="border-input bg-background ring-offset-background focus-visible:ring-ring h-10 w-full rounded-md border px-3 text-sm focus-visible:ring-2 focus-visible:outline-none"
                value={selectedScope}
                onChange={(event) => setScope(event.target.value as NetworkConnectionScope)}
              >
                {scopes.user && <option value="user">{t("scope.user")}</option>}
                {scopes.org && <option value="org">{t("scope.org")}</option>}
              </select>
            </div>
          )}
          {available === false && (
            <p role="note" className="text-muted-foreground text-sm">
              {t("deploymentUnavailable")}
            </p>
          )}
          {error && (
            <p role="alert" className="text-destructive text-sm">
              {error}
            </p>
          )}
          <DialogFooter>
            <Button
              variant="outline"
              type="button"
              onClick={() => onOpenChange(false)}
              disabled={saving}
            >
              {t("cancel")}
            </Button>
            <Button
              type="submit"
              data-tour="tailscale-create-submit"
              loading={saving}
              disabled={!name.trim() || !scopes[selectedScope]}
            >
              {t("create.submit")}
            </Button>
          </DialogFooter>
        </form>
      </DialogContent>
    </Dialog>
  );
}
