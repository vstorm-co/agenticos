"use client";

import { useState } from "react";
import type { ConnectedAccount } from "@/types/mirage";
import { useTranslations } from "next-intl";
import { usePathname } from "next/navigation";
import {
  Button,
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  Checkbox,
  Label,
  Input,
  Select,
  SelectTrigger,
  SelectValue,
  SelectContent,
  SelectItem,
} from "@/components/ui";
import { ErrorState, LoadingState } from "@/components/states";
import { IntegrationProviderSetup } from "./integration-providers";
import { AccountCredentialsSource } from "./account-credentials-source";
import { AddSecretDialog } from "@/components/vault/secret-dialog";
import { useIntegrationSetup } from "@/hooks/use-integration-setup";
import {
  useConnectedAccounts,
  type AccountOwner,
  type IntegrationProvider,
} from "@/hooks/use-connected-accounts";
import { useSecrets } from "@/hooks/use-secrets";
import { usePermissions } from "@/hooks/use-permissions";
import { DIALOG_COLUMN, DIALOG_FORM, DIALOG_BODY } from "@/lib/dialog-sizes";
import { getErrorMessage } from "@/lib/api-error";

export function IntegrationSetupDialog({
  owner,
  provider,
  onClose,
  reconnectAccount,
  initialProducts = [],
  returnTo: oauthReturnTo,
}: {
  owner: AccountOwner;
  provider: Exclude<IntegrationProvider, "imap" | "odoo">;
  onClose: () => void;
  reconnectAccount?: ConnectedAccount;
  initialProducts?: string[];
  returnTo?: string;
}) {
  const t = useTranslations("pages.vault.connectedAccounts.setup");
  const errors = useTranslations("errors");
  const [write, setWrite] = useState(false);
  const [source, setSource] = useState<"own" | "agenticos" | null>(null);
  const setup = useIntegrationSetup(provider, write);
  const { connect, isConnecting, connectToken, connectApplication } = useConnectedAccounts(owner, {
    provider,
  });
  const { can } = usePermissions();
  const allowApplication =
    owner === "organization" || reconnectAccount?.auth_type === "application";
  const secrets = useSecrets({ enabled: allowApplication });
  const [providerSetup, setProviderSetup] = useState(false);
  const [adding, setAdding] = useState(false);
  const [products, setProducts] = useState<string[]>(initialProducts);
  const [token, setToken] = useState("");
  const [label, setLabel] = useState(reconnectAccount?.label ?? "");
  const [method, setMethod] = useState<"oauth" | "application">(
    reconnectAccount?.auth_type === "application" ? "application" : "oauth",
  );
  const [credentialId, setCredentialId] = useState("");
  const [subject, setSubject] = useState(
    reconnectAccount?.auth_type === "application" &&
      (reconnectAccount.email.includes("@") || /^[0-9a-f-]{36}$/i.test(reconnectAccount.email))
      ? reconnectAccount.email
      : "",
  );
  const applicationKind = provider === "google" ? "gcp_service_account" : "entra_app";
  const pathname = usePathname();
  const returnTo = oauthReturnTo ?? pathname;
  const info = setup.data;
  const credentialsSource =
    source ??
    reconnectAccount?.credentials_source ??
    (info?.bridge_status === "ready" && !reconnectAccount ? "agenticos" : "own");
  const oauthReady =
    credentialsSource === "agenticos"
      ? info?.bridge_status === "ready"
      : info?.oauth_client_status === "ready";
  const canChooseApps =
    method !== "oauth" || oauthReady || allowApplication || provider === "slack";
  const scopes =
    info?.products
      .filter((p) => products.includes(p.id))
      .flatMap((p) =>
        method === "application"
          ? write
            ? [...p.application_read_scopes, ...p.application_write_scopes]
            : p.application_read_scopes
          : write
            ? [...p.read_scopes, ...p.write_scopes]
            : p.read_scopes,
      ) ?? [];
  return (
    <>
      <Dialog open onOpenChange={(open) => !open && onClose()}>
        <DialogContent className={`${DIALOG_FORM} ${DIALOG_COLUMN}`}>
          <DialogHeader>
            <DialogTitle>{t("title", { provider: t(`provider.${provider}`) })}</DialogTitle>
            <DialogDescription>{t("description")}</DialogDescription>
          </DialogHeader>
          {setup.isLoading && <LoadingState variant="skeleton-list" rows={2} />}
          {setup.error && <ErrorState description={getErrorMessage(setup.error, errors)} />}
          {info && (
            <div className={`${DIALOG_BODY} space-y-4`}>
              {method === "oauth" && reconnectAccount?.auth_type !== "bearer" && (
                <AccountCredentialsSource
                  value={credentialsSource}
                  available={info.bridge_status === "ready"}
                  locked={!!reconnectAccount}
                  onChange={setSource}
                />
              )}
              {method === "oauth" &&
                credentialsSource === "own" &&
                info.oauth_client_status !== "ready" && (
                  <div className="space-y-2 rounded-lg border p-3">
                    <p className="text-sm">{t("organizationSetupRequired")}</p>
                    {can("secrets:edit") ? (
                      <Button size="sm" variant="outline" onClick={() => setProviderSetup(true)}>
                        {t("configureProvider", { provider: t(`provider.${provider}`) })}
                      </Button>
                    ) : (
                      <p className="text-muted-foreground text-xs">{t("askAdministrator")}</p>
                    )}
                  </div>
                )}
              {provider !== "slack" && allowApplication && (
                <div className="grid gap-3">
                  <div className="flex gap-2">
                    <Button
                      size="sm"
                      variant={method === "oauth" ? "secondary" : "ghost"}
                      disabled={!!reconnectAccount}
                      onClick={() => setMethod("oauth")}
                    >
                      {t("oauth")}
                    </Button>
                    <Button
                      size="sm"
                      variant={method === "application" ? "secondary" : "ghost"}
                      disabled={!!reconnectAccount}
                      onClick={() => setMethod("application")}
                    >
                      {t(provider === "google" ? "serviceAccount" : "application")}
                    </Button>
                  </div>
                  {method === "application" && (
                    <>
                      <p className="text-muted-foreground text-sm">
                        {t(provider === "google" ? "delegation" : "appPermissions")}
                      </p>
                      <Label htmlFor="integration-credential">{t("credential")}</Label>
                      <Select value={credentialId} onValueChange={setCredentialId}>
                        <SelectTrigger id="integration-credential">
                          <SelectValue placeholder={t("chooseCredential")} />
                        </SelectTrigger>
                        <SelectContent>
                          {secrets.secrets
                            .filter((entry) => entry.kind === applicationKind)
                            .map((entry) => (
                              <SelectItem key={entry.id} value={entry.id}>
                                {entry.name}
                              </SelectItem>
                            ))}
                        </SelectContent>
                      </Select>
                      <Label htmlFor="integration-subject">{t("subject")}</Label>
                      <Input
                        id="integration-subject"
                        value={subject}
                        onChange={(e) => setSubject(e.target.value)}
                      />
                    </>
                  )}
                </div>
              )}

              {method === "application" && can("secrets:edit") && (
                <Button variant="outline" onClick={() => setAdding(true)}>
                  {t("saveCredential")}
                </Button>
              )}
              {canChooseApps && (
                <>
                  <div className="grid gap-2">
                    {info.products.map((product) => (
                      <Label key={product.id} className="flex items-center gap-2">
                        <Checkbox
                          checked={products.includes(product.id)}
                          disabled={
                            method === "application" &&
                            !product.application_supported &&
                            !products.includes(product.id)
                          }
                          onCheckedChange={(checked) =>
                            setProducts((current) =>
                              checked
                                ? [...current, product.id]
                                : current.filter((id) => id !== product.id),
                            )
                          }
                        />
                        {product.name}
                      </Label>
                    ))}
                  </div>
                  <Label className="flex items-center gap-2">
                    <Checkbox
                      checked={write}
                      onCheckedChange={(checked) => setWrite(checked === true)}
                    />
                    {t("write")}
                  </Label>
                  <details className="text-xs">
                    <summary>{t("scopes")}</summary>
                    <pre className="mt-2 break-all whitespace-pre-wrap">
                      {[
                        ...new Set([
                          ...(method === "oauth" ? (info?.identity_scopes ?? []) : []),
                          ...scopes,
                        ]),
                      ].join("\n")}
                    </pre>
                  </details>
                  <details className="space-y-2 text-xs">
                    <summary>{t("accountOptions")}</summary>
                    <Label htmlFor="integration-account-label">{t("accountLabel")}</Label>
                    <Input
                      id="integration-account-label"
                      maxLength={64}
                      value={label}
                      onChange={(event) => setLabel(event.target.value)}
                    />
                  </details>
                </>
              )}
              {provider === "slack" &&
                (!reconnectAccount || reconnectAccount.auth_type === "bearer") && (
                  <details
                    className="grid gap-2 text-sm"
                    open={reconnectAccount?.auth_type === "bearer"}
                  >
                    <summary>{t("tokenPath")}</summary>
                    <div className="mt-3 grid gap-2">
                      <Label htmlFor="integration-token">{t("token")}</Label>
                      <Input
                        id="integration-token"
                        type="password"
                        autoComplete="off"
                        value={token}
                        onChange={(e) => setToken(e.target.value)}
                      />
                      <Button
                        variant="outline"
                        disabled={!token || connectToken.isPending}
                        onClick={() =>
                          connectToken.mutate(
                            {
                              token,
                              label,
                              write,
                              ...(reconnectAccount ? { connection_id: reconnectAccount.id } : {}),
                            },
                            {
                              onSuccess: () => {
                                setToken("");
                                onClose();
                              },
                            },
                          )
                        }
                      >
                        {t("saveToken")}
                      </Button>
                    </div>
                  </details>
                )}
              <Button
                disabled={
                  reconnectAccount?.auth_type === "bearer" ||
                  (method === "oauth" && !oauthReady) ||
                  !products.length ||
                  isConnecting ||
                  connectApplication.isPending ||
                  (method === "application" &&
                    (!credentialId ||
                      info.products.some(
                        (p) => products.includes(p.id) && !p.application_supported,
                      )))
                }
                onClick={() =>
                  method === "application"
                    ? connectApplication.mutate(
                        {
                          ...(reconnectAccount ? { connection_id: reconnectAccount.id } : {}),
                          provider,
                          secret_id: credentialId,
                          subject: subject || null,
                          products,
                          write,
                          label,
                        },
                        { onSuccess: onClose },
                      )
                    : connect(returnTo, {
                        ...(credentialsSource === "agenticos"
                          ? { credentials_source: "agenticos" as const }
                          : {}),
                        provider,
                        products,
                        write,
                        label,
                        ...(reconnectAccount ? { connection_id: reconnectAccount.id } : {}),
                      })
                }
              >
                {t("connect")}
              </Button>
            </div>
          )}
        </DialogContent>
      </Dialog>
      {providerSetup && (
        <IntegrationProviderSetup provider={provider} onClose={() => setProviderSetup(false)} />
      )}
      {adding && info && (
        <AddSecretDialog
          open
          onOpenChange={setAdding}
          kinds={secrets.kinds}
          kind={applicationKind}
          isPending={secrets.create.isPending}
          onSubmit={async (data) => {
            const saved = await secrets.create.mutateAsync({ ...data, visibility: "org" });
            if (method === "application") setCredentialId(saved.id);
            setAdding(false);
          }}
        />
      )}
    </>
  );
}
