"use client";

import { useState } from "react";
import { usePathname } from "next/navigation";
import { ChevronDown, Lock, Plug, Plus } from "lucide-react";
import { useTranslations } from "next-intl";
import { PageHeader } from "@/components/dashboard/page-header";
import { VaultTable } from "@/components/vault/vault-table";
import {
  Button,
  ConfirmDialog,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  ListCardEmpty,
} from "@/components/ui";
import { ErrorState } from "@/components/states";
import { SharingPanel } from "@/components/sharing/sharing-panel";
import { AddSecretDialog, RotateSecretDialog } from "@/components/vault/secret-dialog";
import { useMcpOAuthOutcome, usePermissions, useSecretPurposes, useSecrets } from "@/hooks";
import { useConnectedAccounts } from "@/hooks/use-connected-accounts";
import { getErrorMessage } from "@/lib/api-error";
import { Perm } from "@/types/permissions";
import type { Secret } from "@/types/secrets";
import type { ConnectedAccount } from "@/types/mirage";
import { cn } from "@/lib/utils";
import { DIALOG_FORM, DIALOG_SCROLL } from "@/lib/dialog-sizes";

export default function VaultPage() {
  const t = useTranslations("pages.vault");
  const ta = useTranslations("pages.vault.connectedAccounts");
  const tErrors = useTranslations("errors");
  const returnTo = usePathname();
  const {
    secrets,
    kinds,
    isLoading: secretsLoading,
    listError,
    create: createSecret,
    rotate: rotateSecret,
    remove: removeSecret,
  } = useSecrets();
  const { purposes } = useSecretPurposes();
  const { can } = usePermissions();
  const canCreate = can(Perm.secretsEdit);
  const canViewOrganization = can(Perm.connectionsView);
  const canManageOrganization = canViewOrganization && can(Perm.mcpManage);
  const personal = useConnectedAccounts("personal");
  const organization = useConnectedAccounts("organization", { enabled: canViewOrganization });
  const accounts = [...personal.accounts, ...(canViewOrganization ? organization.accounts : [])];
  const loading =
    secretsLoading || personal.isLoading || (canViewOrganization && organization.isLoading);
  const errors = [
    listError,
    personal.error,
    ...(canViewOrganization ? [organization.error] : []),
  ].filter(Boolean);
  const [secretOpen, setSecretOpen] = useState(false);
  const [rotating, setRotating] = useState<Secret | null>(null);
  const [sharing, setSharing] = useState<Secret | null>(null);
  const [disconnecting, setDisconnecting] = useState<ConnectedAccount | null>(null);
  const canManageAccount = (account: ConnectedAccount) =>
    account.owner === "personal" || canManageOrganization;
  const connect = (account: ConnectedAccount) =>
    (account.owner === "personal" ? personal : organization).connect(returnTo);
  useMcpOAuthOutcome();

  return (
    <div className="flex flex-1 flex-col space-y-4">
      <PageHeader
        title={t("vault")}
        description={t("pageDescription")}
        secondaryActions={
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                variant="outline"
                disabled={personal.isConnecting || organization.isConnecting}
              >
                <Plug className="size-4" />
                {t("connectAccount")}
                <ChevronDown className="size-4" />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end">
              <DropdownMenuItem onSelect={() => personal.connect(returnTo)}>
                {t("personalAccount")}
              </DropdownMenuItem>
              {canManageOrganization && (
                <DropdownMenuItem onSelect={() => organization.connect(returnTo)}>
                  {t("organizationAccount")}
                </DropdownMenuItem>
              )}
            </DropdownMenuContent>
          </DropdownMenu>
        }
        actions={
          canCreate ? (
            <Button
              data-tour="vault-new"
              disabled={secretsLoading}
              onClick={() => setSecretOpen(true)}
            >
              <Plus className="size-4" />
              {t("addKey")}
            </Button>
          ) : undefined
        }
      />
      <div data-tour="vault-keys" className="bg-card overflow-hidden rounded-xl border">
        {errors.map((error, index) => (
          <ErrorState key={index} description={getErrorMessage(error, tErrors)} className="m-5" />
        ))}
        {!loading && secrets.length === 0 && accounts.length === 0 ? (
          errors.length === 0 && (
            <ListCardEmpty icon={Lock} title={t("emptyTitle")} description={t("emptyDetail")} />
          )
        ) : (
          <VaultTable
            secrets={secrets}
            purposes={purposes}
            accounts={accounts}
            loading={loading}
            canManageAccount={canManageAccount}
            onShare={setSharing}
            onRotate={setRotating}
            onDelete={(secret) => removeSecret.mutate(secret.id)}
            onReconnectAccount={connect}
            onDisconnectAccount={setDisconnecting}
          />
        )}
      </div>
      {disconnecting && (
        <ConfirmDialog
          open
          onOpenChange={(open) => {
            if (!open) setDisconnecting(null);
          }}
          title={ta("disconnectTitle", { email: disconnecting.email })}
          description={ta("disconnectDetail")}
          confirmLabel={ta("disconnectConfirm")}
          destructive
          onConfirm={() => {
            (disconnecting.owner === "personal" ? personal : organization).disconnect(
              disconnecting.id,
            );
            setDisconnecting(null);
          }}
        />
      )}
      <AddSecretDialog
        open={secretOpen}
        onOpenChange={setSecretOpen}
        kinds={kinds}
        onSubmit={createSecret.mutateAsync}
        isPending={createSecret.isPending}
      />

      {/* Sharing lives behind a per-row dialog rather than a detail page: a
          secret has nothing else to show - the value is unreadable by design -
          so a page for one would be a page containing only this panel. */}
      <Dialog open={sharing !== null} onOpenChange={(open) => !open && setSharing(null)}>
        <DialogContent className={cn(DIALOG_SCROLL, DIALOG_FORM)}>
          <DialogHeader>
            <DialogTitle>{t("accessTo", { name: sharing?.name ?? "" })}</DialogTitle>
            <DialogDescription>{t("whoCanBindKey")}</DialogDescription>
          </DialogHeader>
          {sharing && (
            <SharingPanel
              resourceType="secret"
              resourceId={sharing.id}
              canManage={sharing.can_edit === true}
            />
          )}
        </DialogContent>
      </Dialog>

      <RotateSecretDialog
        secret={rotating}
        onOpenChange={(open) => !open && setRotating(null)}
        kinds={kinds}
        onSubmit={rotateSecret.mutateAsync}
        isPending={rotateSecret.isPending}
      />
    </div>
  );
}
