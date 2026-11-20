"use client";

import { ExternalLink, KeyRound, Plus } from "lucide-react";
import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";

import { Button, Label } from "@/components/ui";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { usePermissions, useSecrets } from "@/hooks";
import { useConnectedAccounts } from "@/hooks/use-connected-accounts";
import { saveDriveResume } from "@/lib/drive-oauth-resume";
import { ROUTES } from "@/lib/constants";
import { hereForMcpOAuthReturn } from "@/lib/mcp-oauth";
import type { ConnectorInfo, SyncSourceCreate } from "@/lib/rag-api";
import { Perm } from "@/types/permissions";

/** The Drive scopes the backend reads with: full access, or read-only. Either lets a source list and sync. */
const DRIVE_SCOPES = [
  "https://www.googleapis.com/auth/drive",
  "https://www.googleapis.com/auth/drive.readonly",
];

/** Choosing an account drops the folder: a folder id means something only in the account it was found through. */
function withAccount(form: SyncSourceCreate, id: string): SyncSourceCreate {
  if (form.connected_account_id === id) return { ...form, secret_id: null };
  return {
    ...form,
    connected_account_id: id,
    secret_id: null,
    config: { ...form.config, folder_id: undefined },
  };
}

/**
 * Which vault credential this source authenticates with.
 *
 * A step of its own because the credential is no longer part of the connector's
 * configuration. It used to be a `secret: true` field in the configure step - a
 * textarea for a service account JSON, two password inputs for an AWS pair -
 * pasted into a JSONB column and encrypted with one deployment-wide key, per
 * source, so one Drive credential feeding five collections was the same JSON
 * pasted five times and rotated in five places (#937).
 *
 * **No inline form.** `InlineSecret` exists for exactly this - adding a key
 * without leaving the page - and it takes `api_key` only, deliberately: an AWS
 * pair and a service-account JSON are multi-field forms with their own
 * validation, and its own docstring says the honest place for those is the
 * Vault. So this offers what the organization holds and a link to go and add
 * one, which is the same answer that component gives for the shapes it does not
 * handle.
 */
export function CredentialStep({
  connector,
  form,
  setForm,
  error,
  resumeFrom = null,
  onResumed,
}: {
  connector: ConnectorInfo;
  form: SyncSourceCreate;
  setForm: React.Dispatch<React.SetStateAction<SyncSourceCreate>>;
  /** What the server said about `secret_id`, if it refused one. */
  error?: string;
  /**
   * The Drive accounts held before a Google consent this step started. When it
   * comes back, the account that is new since is chosen (see `onResumed`).
   */
  resumeFrom?: readonly string[] | null;
  /** Called once the resumed consent has been answered, whether or not it added an account. */
  onResumed?: () => void;
}) {
  const t = useTranslations("rag");
  const { secrets, isLoading, listError } = useSecrets();
  const { can } = usePermissions();
  const isDrive = connector.type === "gdrive";
  const mayViewSecrets = can(Perm.secretsView);
  const mayViewAccounts = isDrive && can(Perm.connectionsView);
  const canConnect = isDrive && can(Perm.connectionsManage);
  const connected = useConnectedAccounts("organization", { enabled: mayViewAccounts });
  // The account path is the first choice for a Drive source whose reader can see
  // the accounts - unless the source already holds a vault credential, which is
  // what it was made with. Derived rather than stored, so it is right once
  // permissions arrive; a click on either choice is kept.
  const [chosenType, setChosenType] = useState<"account" | "secret" | null>(null);
  const credentialType =
    chosenType ??
    (!form.secret_id && (form.connected_account_id || resumeFrom || mayViewAccounts)
      ? "account"
      : "secret");
  const driveAccounts = connected.accounts.filter(
    (account) =>
      account.provider === "google" &&
      !account.needs_reconnect &&
      account.scopes.some((scope) => DRIVE_SCOPES.includes(scope)),
  );
  const newAccountId = resumeFrom
    ? driveAccounts.find((account) => !resumeFrom.includes(account.id))?.id
    : undefined;

  // The account a consent added is the one the reader came back to use. Waits
  // for the list, then answers once either way so the snapshot is not kept.
  useEffect(() => {
    if (!resumeFrom || connected.isLoading) return;
    if (newAccountId !== undefined) setForm((f) => withAccount(f, newAccountId));
    onResumed?.();
  }, [resumeFrom, connected.isLoading, newAccountId, onResumed, setForm]);

  function pickAccount(id: string) {
    setForm((f) => withAccount(f, id));
  }

  /** Saved before the browser leaves, so the wizard can reopen here on its return. */
  function startConnect() {
    const returnTo = hereForMcpOAuthReturn();
    if (returnTo === undefined) return;
    saveDriveResume(
      { ...form, secret_id: null },
      driveAccounts.map((account) => account.id),
    );
    connected.connect(returnTo);
  }

  if (connector.secret_kind === "none") {
    return (
      <div className="border-foreground/10 bg-foreground/[0.03] rounded-xl border p-5 text-center">
        <KeyRound className="text-muted-foreground mx-auto h-6 w-6" />
        <p className="text-foreground/70 mt-3 text-sm">
          {t("credentialNoneNeeded", { name: connector.name })}
        </p>
      </div>
    );
  }

  // Before the picker, not as an empty one: a member who cannot see the
  // organization's credentials is not looking at a list that happens to be
  // empty, and saying so is the difference between "ask somebody" and "add one".
  if (!mayViewSecrets && !mayViewAccounts) {
    return <p className="text-muted-foreground text-sm">{t("credentialNeedsPermission")}</p>;
  }

  // Three states, not two. `secrets` is `[]` while the request is in flight and
  // `[]` when it failed, so deriving straight from it tells somebody the vault
  // holds no credential when the truth is that it could not be read - and sends
  // them to add a duplicate. `.claude/rules/frontend.md` has the rule: an empty
  // page is ambiguous.
  if (credentialType === "secret" && mayViewSecrets && isLoading) {
    return <p className="text-muted-foreground text-sm">{t("credentialLoading")}</p>;
  }
  if (credentialType === "secret" && mayViewSecrets && listError) {
    return <p className="text-destructive text-sm">{t("credentialUnreadable")}</p>;
  }

  const usable = mayViewSecrets
    ? secrets.filter((secret) => secret.kind === connector.secret_kind)
    : [];
  const chosen = form.secret_id ?? "";

  return (
    <div className="space-y-4">
      {isDrive && (
        <div className="flex gap-2" role="group" aria-label={t("driveCredentialType")}>
          <Button
            type="button"
            variant={credentialType === "account" ? "default" : "outline"}
            aria-pressed={credentialType === "account"}
            onClick={() => {
              setChosenType("account");
              setForm((f) => ({ ...f, secret_id: null }));
            }}
          >
            {t("driveUseAccount")}
          </Button>
          <Button
            type="button"
            variant={credentialType === "secret" ? "default" : "outline"}
            aria-pressed={credentialType === "secret"}
            onClick={() => {
              setChosenType("secret");
              setForm((f) => ({ ...f, connected_account_id: null }));
            }}
          >
            {t("driveUseServiceAccount")}
          </Button>
        </div>
      )}

      {isDrive && credentialType === "account" ? (
        <div className="space-y-2">
          {connected.isLoading ? (
            <p className="text-muted-foreground text-sm">{t("driveAccountsLoading")}</p>
          ) : connected.error ? (
            <p className="text-destructive text-sm">{t("driveAccountsUnreadable")}</p>
          ) : (
            <>
              {driveAccounts.length > 0 && (
                <>
                  <Label htmlFor="sync-drive-account">{t("driveAccountLabel")}</Label>
                  <Select value={form.connected_account_id ?? ""} onValueChange={pickAccount}>
                    <SelectTrigger id="sync-drive-account">
                      <SelectValue placeholder={t("driveAccountPlaceholder")} />
                    </SelectTrigger>
                    <SelectContent>
                      {driveAccounts.map((account) => (
                        <SelectItem key={account.id} value={account.id} textValue={account.email}>
                          {account.email}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </>
              )}
              {driveAccounts.length === 0 && (
                <p className="text-muted-foreground text-sm">{t("driveNoAccount")}</p>
              )}
              {driveAccounts.length === 0 && canConnect ? (
                <Button
                  type="button"
                  variant="outline"
                  onClick={startConnect}
                  disabled={connected.isConnecting}
                >
                  <Plus className="h-3.5 w-3.5" aria-hidden />
                  {t("driveConnectGoogle")}
                </Button>
              ) : (
                <a
                  href={ROUTES.VAULT}
                  target="_blank"
                  rel="noreferrer"
                  className="text-foreground inline-flex items-center gap-1 text-sm underline underline-offset-2"
                >
                  {t("driveConnectAccount")}
                  <ExternalLink className="h-3 w-3" />
                </a>
              )}
            </>
          )}
        </div>
      ) : (
        <>
          <p className="text-foreground/65 text-sm">
            {t("credentialIntro", { name: connector.name })}
          </p>

          <div className="space-y-1.5">
            <Label htmlFor="sync-credential">
              {t("credentialLabel")}
              <span className="text-destructive ml-0.5">*</span>
            </Label>
            <Select
              value={chosen}
              onValueChange={(value) => setForm((f) => ({ ...f, secret_id: value }))}
              disabled={usable.length === 0}
            >
              <SelectTrigger
                id="sync-credential"
                {...(error === undefined
                  ? {}
                  : { "aria-invalid": true, "aria-describedby": "sync-credential-error" })}
              >
                <SelectValue placeholder={t("credentialPlaceholder")} />
              </SelectTrigger>
              <SelectContent>
                {usable.map((secret) => (
                  <SelectItem key={secret.id} value={secret.id} textValue={secret.name}>
                    <span className="flex items-center gap-2">
                      <KeyRound className="text-muted-foreground h-3.5 w-3.5" />
                      <span>{secret.name}</span>
                      <span className="text-muted-foreground font-mono text-xs">
                        ··{secret.hint}
                      </span>
                    </span>
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {error !== undefined && (
              <p id="sync-credential-error" className="text-destructive text-xs">
                {error}
              </p>
            )}
          </div>

          {/* A picker with nothing in it and no way to fill it is a dead end, which
            is the state this whole step replaced - the credential was a textarea
            and every source got its own copy. Opened in a new tab so the
            half-filled wizard behind it survives. */}
          <p className="text-muted-foreground text-sm">
            {usable.length === 0
              ? t("credentialNoneStored", { name: connector.name })
              : t("credentialAddAnother")}{" "}
            <a
              href={ROUTES.VAULT}
              target="_blank"
              rel="noreferrer"
              className="text-foreground inline-flex items-center gap-1 underline underline-offset-2"
            >
              {t("credentialOpenVault")}
              <ExternalLink className="h-3 w-3" />
            </a>
          </p>
        </>
      )}
    </div>
  );
}
