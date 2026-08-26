"use client";

import { useState } from "react";
import { toast } from "sonner";

import { EmbeddingProviderFields, useEmbeddingProviders } from "@/components/kb/embedding-picker";
import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui";
import { useChanged } from "@/hooks/use-changed";
import { submitFailure } from "@/lib/api-error";
import { DIALOG_COLUMN, DIALOG_WIDE } from "@/lib/dialog-sizes";
import { cn } from "@/lib/utils";
import type { EmbeddingProviderInput, KnowledgeBase } from "@/types";
import { useTranslations } from "next-intl";

/**
 * Moving a collection's embeddings to another provider of the same model.
 *
 * The model is drawn and not offered, which is the whole shape of this dialog:
 * the vector column was created at its width and every stored vector is in its
 * space, so a collection that changed model would be comparing two spaces as
 * though they meant the same thing. The provider and the key are another
 * matter - the same model served from somewhere else is the same model - and
 * before this there was no way to say so: a rotated key or a move onto an
 * organization's own account meant creating a collection and re-ingesting every
 * document into it.
 *
 * Nothing already indexed changes. That is worth saying on screen, because the
 * dialog looks like it might re-embed and the honest answer is that it re-points
 * the next request.
 */
export function EmbeddingDialog({
  open,
  onOpenChange,
  kb,
  onSave,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  kb: KnowledgeBase;
  onSave: (input: EmbeddingProviderInput) => Promise<unknown>;
}) {
  const t = useTranslations("kb");
  const tErrors = useTranslations("errors");
  const { models, unreadable } = useEmbeddingProviders();
  const [provider, setProvider] = useState(kb.embedding_provider);
  const [secretId, setSecretId] = useState<string | null>(kb.embedding_secret_id);
  const [isSaving, setIsSaving] = useState(false);
  const [errors, setErrors] = useState<Readonly<Record<string, string>>>({});

  // Reopening shows what the server holds, not what was abandoned last time -
  // and a save elsewhere must not leave a stale draft to be posted over it.
  // Both called unconditionally and combined after: `||` would skip the second.
  const opened = useChanged(open);
  const rowMoved = useChanged(kb);
  if (opened || rowMoved) {
    setProvider(kb.embedding_provider);
    setSecretId(kb.embedding_secret_id);
    setErrors({});
  }

  // Only providers that serve this collection's model at its recorded width. A
  // list of every provider would offer moves the server refuses, and the reason
  // it refuses them is not something a person should have to discover twice.
  const usable = (models?.providers ?? []).filter((entry) =>
    entry.models.some(
      (model) => model.model === kb.embedding_model && model.dim === kb.embedding_dim,
    ),
  );
  const moved = provider !== kb.embedding_provider || secretId !== kb.embedding_secret_id;

  const save = async () => {
    setIsSaving(true);
    try {
      await onSave({
        embedding_provider: provider,
        // Two different things to say, so two fields: null means "leave the key
        // alone" on a partial update, and going back to the deployment's key has
        // to be sayable as well.
        ...(secretId === null
          ? { clear_embedding_secret: true }
          : { embedding_secret_id: secretId }),
      });
      onOpenChange(false);
    } catch (error) {
      const failure = submitFailure(
        error,
        { fields: ["embedding_provider", "embedding_secret_id"] },
        tErrors,
      );
      setErrors(failure.fields);
      if (failure.toast) toast.error(failure.toast);
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className={cn(DIALOG_COLUMN, DIALOG_WIDE)}>
        <DialogHeader>
          <DialogTitle>{t("embeddings")}</DialogTitle>
          <DialogDescription>{t("providerMoveKeepsTheIndex")}</DialogDescription>
        </DialogHeader>
        <div className="-mx-1 min-h-0 flex-1 scrollbar-thin space-y-4 overflow-y-auto px-1">
          <div className="border-border space-y-1 rounded-lg border p-3">
            <p className="text-muted-foreground text-xs">{t("modelIsFixed")}</p>
            <p className="font-mono text-sm">{kb.embedding_model}</p>
            <p className="text-muted-foreground text-xs">
              {t("dimensions", { count: kb.embedding_dim })}
            </p>
          </div>
          {models === undefined ? (
            unreadable ? (
              <p className="text-destructive text-sm">{t("modelsUnreadable")}</p>
            ) : (
              <p className="text-muted-foreground text-sm">{t("loadingModels")}</p>
            )
          ) : (
            <>
              <EmbeddingProviderFields
                models={{ ...models, providers: usable }}
                provider={provider}
                secretId={secretId}
                onProvider={setProvider}
                onSecretId={setSecretId}
                idPrefix="kb-embedding"
              />
              {(errors.embedding_provider ?? errors.embedding_secret_id) !== undefined && (
                <p className="text-destructive text-xs">
                  {errors.embedding_provider ?? errors.embedding_secret_id}
                </p>
              )}
            </>
          )}
        </div>
        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            {t("cancel")}
          </Button>
          <Button type="button" onClick={save} disabled={!moved || isSaving}>
            {isSaving ? t("saving") : t("save")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
