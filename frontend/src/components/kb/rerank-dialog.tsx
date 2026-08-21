"use client";

import { useState } from "react";
import { toast } from "sonner";

import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { InlineSecret } from "@/components/vault/inline-secret";
import { ProviderRow } from "@/components/vault/provider-row";
import { useSecrets } from "@/hooks";
import { useChanged } from "@/hooks/use-changed";
import { submitFailure } from "@/lib/api-error";
import { DEFAULT_RERANK_MODEL, RERANK_KEY_PURPOSE, RERANK_OFF } from "@/lib/rerank-config";
import type { UpdateRerankInput } from "@/types";
import { useTranslations } from "next-intl";

interface RerankDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** The rerank key the collection is set to now, or null when reranking is off. */
  rerankSecretId: string | null;
  collectionName: string;
  onSave: (input: UpdateRerankInput) => Promise<unknown>;
}

/**
 * Turning reranking on, changing its key, or turning it off on an existing
 * collection.
 *
 * A dialog rather than an inline control for the same reason the ingestion one
 * is: the change is a decision with a cost attached (a rerank key is billed per
 * search), and it takes effect from the next search rather than reshuffling what
 * is already on screen. The model is not a choice - there is one reranker - so
 * the only field is which key pays, and "off" is one of its options.
 */
export function RerankDialog({
  open,
  onOpenChange,
  rerankSecretId,
  collectionName,
  onSave,
}: RerankDialogProps) {
  const tErrors = useTranslations("errors");
  const t = useTranslations("kb");
  const { secrets } = useSecrets();
  const rerankKeys = secrets.filter((secret) => secret.purpose === RERANK_KEY_PURPOSE);
  const [draftSecretId, setDraftSecretId] = useState<string | null>(rerankSecretId);
  const [isSaving, setIsSaving] = useState(false);
  const [errors, setErrors] = useState<Readonly<Record<string, string>>>({});

  // Reopening shows what the server holds, not a draft abandoned last time - and
  // a change made elsewhere must not leave a stale pick to be posted back over.
  const opened = useChanged(open);
  const secretMoved = useChanged(rerankSecretId);
  if (opened || secretMoved) {
    if (open) {
      setDraftSecretId(rerankSecretId);
      setErrors({});
    }
  }

  const changed = draftSecretId !== rerankSecretId;

  const handleSave = async () => {
    setIsSaving(true);
    try {
      // The pair the backend reads together: a key turns reranking on with the
      // one model there is, no key turns it off. Both are always sent, so the
      // update is unambiguously "change reranking" rather than "leave it".
      await onSave({
        rerank_model: draftSecretId ? DEFAULT_RERANK_MODEL : null,
        rerank_secret_id: draftSecretId,
      });
      onOpenChange(false);
    } catch (err) {
      const failure = submitFailure(err, { fields: ["rerank_secret_id"] }, tErrors);
      setErrors(failure.fields);
      if (failure.toast) toast.error(failure.toast);
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="sm:max-w-lg">
        <DialogHeader>
          <DialogTitle>{t("rerankSettings")}</DialogTitle>
          <DialogDescription>
            {t.rich("rerankSettingsDescription", {
              name: collectionName,
              mono: (chunks) => <span className="text-foreground font-mono text-xs">{chunks}</span>,
            })}
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-1.5">
          <Label htmlFor="kb-rerank-edit-key">{t("rerankKey")}</Label>
          <Select
            value={draftSecretId ?? RERANK_OFF}
            onValueChange={(v) => setDraftSecretId(v === RERANK_OFF ? null : v)}
          >
            <SelectTrigger id="kb-rerank-edit-key">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value={RERANK_OFF}>{t("rerankOff")}</SelectItem>
              {rerankKeys.map((secret) => (
                <SelectItem key={secret.id} value={secret.id} textValue={secret.name}>
                  <ProviderRow
                    provider={RERANK_KEY_PURPOSE}
                    name={secret.name}
                    hint={secret.hint}
                  />
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {errors.rerank_secret_id && (
            <p className="text-destructive text-sm">{errors.rerank_secret_id}</p>
          )}
          <p className="text-muted-foreground text-xs">{t("rerankHelp")}</p>
          <InlineSecret
            kind="api_key"
            purpose={RERANK_KEY_PURPOSE}
            suggestedName={t("rerankKeyName")}
            onCreated={setDraftSecretId}
          />
        </div>

        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            {t("cancel2")}
          </Button>
          <Button type="button" onClick={handleSave} disabled={!changed || isSaving}>
            {isSaving ? t("saving") : t("save")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
