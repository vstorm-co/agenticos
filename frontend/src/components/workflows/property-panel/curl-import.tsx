"use client";

import { useState } from "react";
import { KeyRound, Terminal } from "lucide-react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Textarea,
} from "@/components/ui";
import { AddSecretDialog } from "@/components/vault/secret-dialog";
import { usePermissions, useSecrets } from "@/hooks";
import { DIALOG_FORM } from "@/lib/dialog-sizes";
import { type CurlCredential, parseCurl } from "@/lib/workflows/curl";
import type { Binding, NodeInstance, Uuid } from "@/lib/workflows/types";
import { Perm } from "@/types/permissions";

/** Where the lifted credential may be sent, and what it is. */
interface Lifted {
  credential: CurlCredential;
  origin: string;
  host: string;
}

/** How the step sends a lifted credential - its auth block, less the secret. */
function authOf(credential: CurlCredential): Record<string, string> {
  if (credential.kind === "header") return { kind: "header", header_name: credential.name };
  if (credential.kind === "query") return { kind: "query", query_name: credential.name };
  return { kind: credential.kind };
}

/**
 * **Import cURL** on an HTTP step: a command pasted from an API's docs fills the
 * method, URL, headers and JSON body. A credential in it is never written into
 * the step - it is lifted out, and the step is set to send it the same way once
 * it is stored in the vault, which the dialog offers next with the token
 * already in the form.
 */
export function CurlImport({
  node,
  disabled,
  updateNodeConfig,
  upsertBinding,
}: {
  node: NodeInstance;
  disabled: boolean;
  updateNodeConfig: (nodeId: Uuid, config: Record<string, unknown>) => void;
  upsertBinding: (binding: Binding) => void;
}) {
  const t = useTranslations("workflows");
  const { kinds, create } = useSecrets();
  const { can } = usePermissions();
  const [open, setOpen] = useState(false);
  const [text, setText] = useState("");
  const [problem, setProblem] = useState<string | null>(null);
  const [lifted, setLifted] = useState<Lifted | null>(null);
  const [storing, setStoring] = useState(false);

  const close = () => {
    setOpen(false);
    setText("");
    setProblem(null);
    setLifted(null);
    setStoring(false);
  };

  const apply = () => {
    const parsed = parseCurl(text);
    if (typeof parsed === "string") {
      setProblem(t(`curlProblem.${parsed}`));
      return;
    }
    // The command's headers replace the step's; its auth stays unless the
    // command says how it authenticates.
    const next: Record<string, unknown> = { ...node.config, method: parsed.method };
    delete next["headers"];
    if (Object.keys(parsed.headers).length > 0) next["headers"] = parsed.headers;
    if (parsed.credential !== null) next["auth"] = authOf(parsed.credential);
    updateNodeConfig(node.id, next);
    const literal = (field: string, value: unknown) =>
      upsertBinding({
        target_node_id: node.id,
        target_field: field,
        source: { kind: "literal", value },
      });
    literal("url", parsed.url);
    if (parsed.body !== undefined) literal("body", parsed.body);
    if (parsed.droppedBody) toast.warning(t("curlDroppedBody"));
    // The command holds the credential too: gone from here the moment it is read.
    setText("");
    if (parsed.credential === null) {
      toast.success(t("curlImported"));
      close();
      return;
    }
    const address = new URL(parsed.url);
    setLifted({ credential: parsed.credential, origin: address.origin, host: address.host });
  };

  const store = async (data: Parameters<typeof create.mutateAsync>[0]) => {
    const secret = await create.mutateAsync(data);
    const auth = { ...(node.config["auth"] as Record<string, unknown>), secret_id: secret.id };
    updateNodeConfig(node.id, { ...node.config, auth });
    close();
  };

  return (
    <>
      <Button
        type="button"
        size="sm"
        variant="outline"
        disabled={disabled}
        onClick={() => setOpen(true)}
      >
        <Terminal className="size-3.5" />
        {t("curlImport")}
      </Button>
      <Dialog open={open && !storing} onOpenChange={(next) => !next && close()}>
        <DialogContent className={DIALOG_FORM}>
          <DialogHeader>
            <DialogTitle>{t("curlTitle")}</DialogTitle>
            <DialogDescription>
              {lifted === null ? t("curlDescription") : t("curlImported")}
            </DialogDescription>
          </DialogHeader>
          {lifted === null ? (
            <div className="space-y-2">
              <Textarea
                aria-label={t("curlCommand")}
                value={text}
                onChange={(event) => {
                  setText(event.target.value);
                  setProblem(null);
                }}
                // i18n-exempt: a sample command, not console copy
                placeholder="curl https://api.example.com/v1/items -H 'Accept: application/json'"
                className="min-h-40 font-mono text-xs"
              />
              {problem !== null && <p className="text-destructive text-xs">{problem}</p>}
            </div>
          ) : (
            <p className="border-border flex gap-2 rounded-lg border px-3 py-2.5 text-sm">
              <KeyRound className="mt-0.5 size-4 shrink-0" />
              {can(Perm.secretsEdit)
                ? t("curlCredential", { kind: lifted.credential.kind })
                : t("curlCredentialNoRight", { kind: lifted.credential.kind })}
            </p>
          )}
          <DialogFooter>
            <Button variant="outline" onClick={close}>
              {lifted === null ? t("curlCancel") : t("curlNotNow")}
            </Button>
            {lifted === null ? (
              <Button onClick={apply} disabled={text.trim() === ""}>
                {t("curlImportAction")}
              </Button>
            ) : (
              can(Perm.secretsEdit) && (
                <Button onClick={() => setStoring(true)}>{t("curlStore")}</Button>
              )
            )}
          </DialogFooter>
        </DialogContent>
      </Dialog>
      {lifted !== null && storing && (
        <AddSecretDialog
          open
          onOpenChange={(next) => !next && setStoring(false)}
          kinds={kinds}
          kind="http_credential"
          isPending={create.isPending}
          initial={{
            name: t("curlSecretName", { host: lifted.host }),
            value: {
              token: lifted.credential.token,
              ...(lifted.credential.kind === "basic"
                ? { username: lifted.credential.username }
                : {}),
              origins: [lifted.origin],
            },
          }}
          onSubmit={store}
        />
      )}
    </>
  );
}
