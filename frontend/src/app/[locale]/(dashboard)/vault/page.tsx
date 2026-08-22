"use client";

import { useState } from "react";
import { Lock, Plus } from "lucide-react";

import { PageHeader } from "@/components/dashboard/page-header";
import { SecretsTable } from "@/components/vault/secrets-table";
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  ListCard,
  ListCardEmpty,
  Skeleton,
} from "@/components/ui";
import { ErrorState } from "@/components/states";
import { SharingPanel } from "@/components/sharing/sharing-panel";
import { AddSecretDialog, RotateSecretDialog } from "@/components/vault/secret-dialog";
import { usePermissions, useSecretPurposes, useSecrets } from "@/hooks";
import { getErrorMessage } from "@/lib/api-error";
import { Perm } from "@/types/permissions";
import type { Secret } from "@/types/secrets";
import { useTranslations } from "next-intl";
import { cn } from "@/lib/utils";
import { DIALOG_FORM, DIALOG_SCROLL } from "@/lib/dialog-sizes";

/**
 * One sentence, in one place, so the skeleton and the page cannot disagree -
 * a header that changes text when the data lands is a flicker nobody asked for.
 */
const VAULT_DESCRIPTION = "pageDescription";

export default function VaultPage() {
  const t = useTranslations("pages.vault");
  const tErrors = useTranslations("errors");
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
  // The backend gates writes on secrets:edit, not connections:manage - a
  // Member holds it at OWN scope, so the "Add key" button must not vanish
  // for them.
  const canManage = can(Perm.secretsEdit);

  const [secretOpen, setSecretOpen] = useState(false);
  const [rotating, setRotating] = useState<Secret | null>(null);
  const [sharing, setSharing] = useState<Secret | null>(null);

  // The same card the page renders, with row skeletons in it. A skeleton that
  // draws a different shape from what follows is a layout jump on every load.
  if (secretsLoading)
    return (
      <div className="space-y-6">
        <PageHeader title={t("vault")} description={t(VAULT_DESCRIPTION)} />
        <ListCard title={t("keys")} counted={null} contentClassName="p-0">
          {[0, 1, 2].map((row) => (
            <div
              key={row}
              className="border-border flex items-center gap-3 border-b px-5 py-4 last:border-b-0"
            >
              <Skeleton className="h-8 w-8 shrink-0 rounded-lg" />
              <div className="min-w-0 flex-1 space-y-2">
                <Skeleton className="h-4 w-40" />
                <Skeleton className="h-3 w-72 max-w-full" />
              </div>
            </div>
          ))}
        </ListCard>
      </div>
    );

  return (
    <div className="space-y-6">
      <PageHeader
        title={t("vault2")}
        description={t(VAULT_DESCRIPTION)}
        actions={
          canManage ? (
            <Button data-tour="vault-new" onClick={() => setSecretOpen(true)}>
              <Plus className="h-4 w-4" />
              {t("addKey")}
            </Button>
          ) : undefined
        }
      />

      <ListCard
        data-tour="vault-keys"
        title={t("keys")}
        // With the list refused, "0 keys stored" would state as fact something
        // the request never answered - the skeleton stays.
        counted={listError ? null : t("storedCount", { count: secrets.length })}
        contentClassName="p-0"
      >
        {listError ? (
          <ErrorState description={getErrorMessage(listError, tErrors)} className="m-5" />
        ) : secrets.length === 0 ? (
          <ListCardEmpty
            icon={Lock}
            title={t("noKeysYet")}
            description={t("addOneBecomesSelectable")}
            cta={
              canManage
                ? {
                    label: (
                      <>
                        <Plus className="h-3.5 w-3.5" />
                        {t("addKey2")}
                      </>
                    ),
                    onClick: () => setSecretOpen(true),
                  }
                : undefined
            }
          />
        ) : (
          <SecretsTable
            secrets={secrets}
            purposes={purposes}
            canManage={canManage}
            onShare={setSharing}
            onRotate={setRotating}
            onDelete={(secret) => removeSecret.mutate(secret.id)}
          />
        )}
      </ListCard>

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
            <SharingPanel resourceType="secret" resourceId={sharing.id} canManage={canManage} />
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
