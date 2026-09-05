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
  Input,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Textarea,
} from "@/components/ui";
import { useMemoryFacts } from "@/hooks/use-memory";
import { useAuth } from "@/hooks/use-auth";
import { submitFailure } from "@/lib/api-error";
import { cn } from "@/lib/utils";
import { useTranslations } from "next-intl";
import { DIALOG_FORM } from "@/lib/dialog-sizes";

/** What the backend accepts, so an over-long value is refused before it is sent. */
const MAX_CONTENT = 2000;
const MAX_SCOPE_KEY = 128;

type Store = "org" | "owned";

interface CreateMemoryFactDialogProps {
  agentId: string;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Whether the caller may write the organisation's store and other owners'. */
  canEdit: boolean;
}

/**
 * New operator-seeded fact — a sentence embedded server-side so `recall` finds it
 * by meaning. The one exception to "operators never author facts": seeding standing
 * semantic knowledge is a deliberate management act (the embedding books to the
 * organisation's ingestion spend rather than a run's, the same as a RAG document).
 * Scope works exactly as it does for a file: shared is an operator act, personal
 * defaults to the caller's own key and a member may seed only that; the backend
 * re-checks regardless of what the dialog offers.
 */
export function CreateMemoryFactDialog({
  agentId,
  open,
  onOpenChange,
  canEdit,
}: CreateMemoryFactDialogProps) {
  const tErrors = useTranslations("errors");
  const t = useTranslations("memory");
  const { create } = useMemoryFacts({ agentId });
  const { user } = useAuth();
  const ownKey = user ? `person:${user.id}` : null;

  const [content, setContent] = useState("");
  const [store, setStore] = useState<Store>(canEdit ? "org" : "owned");
  const [ownerKey, setOwnerKey] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [ownerError, setOwnerError] = useState<string | null>(null);

  const resolvedOwnerKey = store === "org" ? null : canEdit ? ownerKey.trim() || ownKey : ownKey;
  const ownerReady = store === "org" || resolvedOwnerKey !== null;

  function reset() {
    setContent("");
    setStore(canEdit ? "org" : "owned");
    setOwnerKey("");
    setError(null);
    setOwnerError(null);
  }

  async function handleCreate() {
    try {
      await create.mutateAsync({ content, owner_key: resolvedOwnerKey });
      reset();
      onOpenChange(false);
    } catch (err) {
      const failure = submitFailure(err, { fields: ["content", "owner_key"] }, tErrors);
      setError(failure.fields.content ?? null);
      setOwnerError(failure.fields.owner_key ?? null);
      if (failure.toast) toast.error(failure.toast);
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className={DIALOG_FORM}>
        <DialogHeader>
          <DialogTitle>{t("newFact")}</DialogTitle>
          <DialogDescription>{t("newFactHint")}</DialogDescription>
        </DialogHeader>

        <div className="space-y-4">
          <div className="flex flex-wrap items-start gap-4">
            {canEdit ? (
              <div className="w-40 shrink-0 space-y-1.5">
                <Label htmlFor="new-fact-store">{t("storeLabel")}</Label>
                <Select value={store} onValueChange={(value) => setStore(value as Store)}>
                  <SelectTrigger id="new-fact-store">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="org">{t("storeOrg")}</SelectItem>
                    <SelectItem value="owned">{t("storeOwned")}</SelectItem>
                  </SelectContent>
                </Select>
              </div>
            ) : null}
            {store === "owned" && canEdit ? (
              <div className="min-w-56 flex-1 space-y-1.5">
                <Label htmlFor="new-fact-scope">{t("ownerKeyLabel")}</Label>
                <Input
                  id="new-fact-scope"
                  value={ownerKey}
                  onChange={(event) => {
                    setOwnerKey(event.target.value);
                    if (ownerError) setOwnerError(null);
                  }}
                  placeholder={ownKey ?? "user:<id>"}
                  maxLength={MAX_SCOPE_KEY}
                  className="font-mono"
                  aria-invalid={ownerError ? true : undefined}
                />
                <p
                  className={cn(
                    "text-xs",
                    ownerError ? "text-destructive" : "text-muted-foreground",
                  )}
                >
                  {ownerError ?? t("ownerKeyNote")}
                </p>
              </div>
            ) : null}
          </div>

          {store === "owned" && !canEdit ? (
            <p className="text-muted-foreground text-xs">{t("personalOwnNote")}</p>
          ) : null}

          <div className="space-y-1.5">
            <Label htmlFor="new-fact-content">{t("factContentLabel")}</Label>
            <Textarea
              id="new-fact-content"
              value={content}
              onChange={(event) => {
                setContent(event.target.value);
                if (error) setError(null);
              }}
              placeholder={t("factContentPlaceholder")}
              maxLength={MAX_CONTENT}
              rows={4}
              aria-invalid={error ? true : undefined}
            />
            <p className={cn("text-xs", error ? "text-destructive" : "text-muted-foreground")}>
              {error ?? t("factContentNote")}
            </p>
          </div>
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            {t("cancel")}
          </Button>
          <Button
            onClick={handleCreate}
            disabled={!content.trim() || !ownerReady || create.isPending}
          >
            {t("create")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
