"use client";

import { useState } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";
import {
  Badge,
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui";
import { ErrorState, LoadingState } from "@/components/states";
import { Settings2 } from "lucide-react";
import { useIntegrationSetup } from "@/hooks/use-integration-setup";
import { useSecrets } from "@/hooks/use-secrets";
import { usePermissions } from "@/hooks/use-permissions";
import { getErrorMessage } from "@/lib/api-error";
import { ROUTES } from "@/lib/constants";
import { DIALOG_COLUMN, DIALOG_FORM, DIALOG_BODY } from "@/lib/dialog-sizes";
import { ProviderIcon } from "./provider-icon";
import { ProviderRegistrationSteps } from "./provider-registration-steps";
import { AddSecretDialog } from "./secret-dialog";

type OAuthProvider = "google" | "microsoft" | "slack";
const PROVIDERS: readonly OAuthProvider[] = ["google", "microsoft", "slack"];

/** Organization setup is separate from each person's account consent. */
export function IntegrationProviders() {
  const t = useTranslations("pages.vault.connectedAccounts.setup");
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState<OAuthProvider | null>(null);
  return (
    <>
      <Button
        variant="outline"
        data-tour="integration-provider-setup"
        onClick={() => setOpen(true)}
      >
        <Settings2 className="size-4" aria-hidden />
        {t("manageIntegrations")}
      </Button>
      <Dialog open={open && selected === null} onOpenChange={setOpen}>
        <DialogContent className={DIALOG_FORM}>
          <DialogHeader>
            <DialogTitle>{t("adminTitle")}</DialogTitle>
            <DialogDescription>{t("adminDescription")}</DialogDescription>
          </DialogHeader>
          {open && (
            <div className="space-y-2">
              {PROVIDERS.map((provider) => (
                <ProviderSetupRow
                  key={provider}
                  provider={provider}
                  onConfigure={() => setSelected(provider)}
                />
              ))}
            </div>
          )}
        </DialogContent>
      </Dialog>
      {selected && (
        <IntegrationProviderSetup provider={selected} onClose={() => setSelected(null)} />
      )}
    </>
  );
}

function ProviderSetupRow({
  provider,
  onConfigure,
}: {
  provider: OAuthProvider;
  onConfigure: () => void;
}) {
  const t = useTranslations("pages.vault.connectedAccounts.setup");
  const errors = useTranslations("errors");
  const { can } = usePermissions();
  const setup = useIntegrationSetup(provider);
  return (
    <div className="rounded-xl border p-3">
      <div className="flex flex-wrap items-center gap-3">
        <ProviderIcon provider={provider} brand={provider} />
        <span className="min-w-0 flex-1 text-sm font-medium">{t(`provider.${provider}`)}</span>
        {setup.data && (
          <Badge variant="outline">{t(`clientStatus.${setup.data.oauth_client_status}`)}</Badge>
        )}
        {can("secrets:edit") && (
          <Button size="sm" variant="outline" onClick={onConfigure} disabled={!setup.data}>
            {t("configureProvider", { provider: t(`provider.${provider}`) })}
          </Button>
        )}
      </div>
      {setup.isLoading && <LoadingState variant="skeleton-list" rows={1} />}
      {setup.error && <ErrorState description={getErrorMessage(setup.error, errors)} />}
    </div>
  );
}

export function IntegrationProviderSetup({
  provider,
  onClose,
}: {
  provider: OAuthProvider;
  onClose: () => void;
}) {
  const t = useTranslations("pages.vault.connectedAccounts.setup");
  const errors = useTranslations("errors");
  const { can } = usePermissions();
  const setup = useIntegrationSetup(provider, true);
  const secrets = useSecrets({ enabled: can("secrets:edit") });
  const [adding, setAdding] = useState(false);
  const info = setup.data;
  return (
    <>
      <Dialog open onOpenChange={(open) => !open && onClose()}>
        <DialogContent className={`${DIALOG_FORM} ${DIALOG_COLUMN}`}>
          <DialogHeader>
            <DialogTitle>
              {t("configureProvider", { provider: t(`provider.${provider}`) })}
            </DialogTitle>
            <DialogDescription>{t("adminDescription")}</DialogDescription>
          </DialogHeader>
          {setup.error && <ErrorState description={getErrorMessage(setup.error, errors)} />}
          {info && (
            <div className={`${DIALOG_BODY} space-y-4`}>
              <ProviderRegistrationSteps
                provider={provider}
                redirectUri={info.redirect_uri}
                consoleUrl={info.manifest_url ?? info.console_url}
                enableApisCommand={info.enable_apis_command}
              />
              <details className="text-xs">
                <summary>{t("scopes")}</summary>
                <pre className="mt-2 break-all whitespace-pre-wrap">
                  {[
                    ...new Set([
                      ...info.identity_scopes,
                      ...info.products.flatMap((product) => [
                        ...product.read_scopes,
                        ...product.write_scopes,
                      ]),
                    ]),
                  ].join("\n")}
                </pre>
              </details>
              <p className="text-muted-foreground text-sm">
                {t(`clientStatus.${info.oauth_client_status}`)}
              </p>
              {info.oauth_client_status === "missing" && can("secrets:edit") ? (
                <Button onClick={() => setAdding(true)}>{t("saveClient")}</Button>
              ) : (
                <Button variant="outline" asChild>
                  <Link href={ROUTES.VAULT} onClick={onClose}>
                    {t("manageCredentials")}
                  </Link>
                </Button>
              )}
            </div>
          )}
        </DialogContent>
      </Dialog>
      {adding && info && (
        <AddSecretDialog
          open
          onOpenChange={setAdding}
          kinds={secrets.kinds}
          kind={info.secret_kind}
          isPending={secrets.create.isPending}
          onSubmit={async (data) => {
            await secrets.create.mutateAsync({ ...data, visibility: "org" });
            setAdding(false);
          }}
        />
      )}
    </>
  );
}
