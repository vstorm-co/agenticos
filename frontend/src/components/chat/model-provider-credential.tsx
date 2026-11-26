"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Button } from "@/components/ui";
import { InlineSecret } from "@/components/vault/inline-secret";
import { InlineChatGPTSignIn } from "@/components/vault/chatgpt-sign-in";
import { AddSecretDialog } from "@/components/vault/secret-dialog";
import { usePermissions, useSecrets } from "@/hooks";
import { isChatGPTSignInKind, type SecretPurpose } from "@/types/secrets";
import { Perm } from "@/types/permissions";

/** Reuse the vault's credential shapes and permission checks inside model selection. */
export function ModelProviderCredential({
  provider,
  onCreated,
}: {
  provider: SecretPurpose;
  onCreated: () => void;
}) {
  if (isChatGPTSignInKind(provider.kind))
    return (
      <InlineChatGPTSignIn
        key={provider.id}
        kind={provider.kind}
        suggestedName={provider.label}
        onCreated={onCreated}
      />
    );
  if (provider.kind === "api_key")
    return (
      <InlineSecret
        kind="api_key"
        purpose={provider.id}
        suggestedName={provider.label}
        helpUrl={provider.help_url ?? undefined}
        onCreated={onCreated}
      />
    );
  return <StructuredCredential key={provider.id} provider={provider} onCreated={onCreated} />;
}

function StructuredCredential({
  provider,
  onCreated,
}: {
  provider: SecretPurpose;
  onCreated: () => void;
}) {
  const t = useTranslations("vault");
  const [open, setOpen] = useState(false);
  const { can } = usePermissions();
  const { kinds, create } = useSecrets();
  if (!can(Perm.secretsEdit))
    return <p className="text-muted-foreground text-xs">{t("storingNeedsPermission")}</p>;
  return (
    <>
      <Button type="button" variant="outline" size="sm" onClick={() => setOpen(true)}>
        {t("addKeyNamed", { name: provider.label })}
      </Button>
      {open && (
        <AddSecretDialog
          open
          onOpenChange={setOpen}
          kinds={kinds}
          purposeId={provider.id}
          initial={{ name: provider.label }}
          isPending={create.isPending}
          onSubmit={async (data) => {
            await create.mutateAsync(data);
            setOpen(false);
            onCreated();
          }}
        />
      )}
    </>
  );
}
