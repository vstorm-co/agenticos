"use client";

import { useState } from "react";
import type { ReactNode } from "react";
import { Lock, Plus } from "lucide-react";

import { PageHeader } from "@/components/dashboard/page-header";
import { SecretsTable } from "@/components/vault/secrets-table";
import {
  Button,
  Card,
  CardContent,
  CardDescription,
  Dialog,
  DialogContent,
  DialogDescription,
  CardHeader,
  CardTitle,
  DialogHeader,
  DialogTitle,
  Skeleton,
} from "@/components/ui";
import { SharingPanel } from "@/components/sharing/sharing-panel";
import { AddSecretDialog, RotateSecretDialog } from "@/components/vault/secret-dialog";
import { usePermissions, useSecretPurposes, useSecrets } from "@/hooks";
import { Perm } from "@/types/permissions";
import type { Secret } from "@/types/secrets";
import { useTranslations } from "next-intl";

/**
 * One sentence, in one place, so the skeleton and the page cannot disagree -
 * a header that changes text when the data lands is a flicker nobody asked for.
 */
const VAULT_DESCRIPTION = "pageDescription";

/**
 * The list's frame, drawn whether or not there is anything in it.
 *
 * The card used to be a container around the empty state and a bare stack of
 * rows once a key existed, which reads as the panel disappearing the moment you
 * use it. Same header, same border, in every state: what changes is what is
 * inside it.
 */
function KeysCard({ count, children }: { count: number | null; children: ReactNode }) {
  const t = useTranslations("pages.vault");
  return (
    <Card>
      <CardHeader className="flex-row items-center justify-between space-y-0 border-b px-5 py-4">
        <div className="space-y-1">
          <CardTitle className="text-sm">{t("keys")}</CardTitle>
          <CardDescription className="text-xs">
            {/* `null` is "the request has not answered". Rendering "0 keys
                stored" there would state something about the organization that
                nothing has said yet - and it is the one number somebody would
                read as fact. */}
            {count === null ? <Skeleton className="h-3 w-24" /> : t("storedCount", { count })}
          </CardDescription>
        </div>
      </CardHeader>
      <CardContent className="p-0">{children}</CardContent>
    </Card>
  );
}

export default function VaultPage() {
  const t = useTranslations("pages.vault");
  const {
    secrets,
    kinds,
    isLoading: secretsLoading,
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
        <KeysCard count={null}>
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
        </KeysCard>
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

      <KeysCard count={secrets.length}>
        {secrets.length === 0 ? (
          // Inline rather than an `EmptyState`: that component draws its own
          // bordered box, and inside a card it made two frames around one
          // message with two hundred pixels of nothing between them.
          <div className="px-6 py-16 text-center">
            <div className="bg-muted text-muted-foreground mx-auto flex h-11 w-11 items-center justify-center rounded-xl">
              <Lock className="h-5 w-5" />
            </div>
            <p className="text-foreground mt-4 text-sm font-medium">{t("noKeysYet")}</p>
            <p className="text-muted-foreground mx-auto mt-1 max-w-sm text-sm">
              {t("addOneBecomesSelectable")}
            </p>
            {canManage && (
              <Button
                variant="outline"
                size="sm"
                className="mt-5"
                onClick={() => setSecretOpen(true)}
              >
                <Plus className="h-3.5 w-3.5" />
                {t("addKey2")}
              </Button>
            )}
          </div>
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
      </KeysCard>

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
        <DialogContent className="max-h-[85vh] overflow-y-auto sm:max-w-2xl">
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
