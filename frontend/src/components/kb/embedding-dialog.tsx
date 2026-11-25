"use client";

import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { toast } from "sonner";

import {
  EmbeddingProviderFields,
  useEmbeddingProviders,
  useEndpointEmbeddingModels,
} from "@/components/kb/embedding-picker";
import { ProbeResult } from "@/components/kb/probe-result";
import { ProbeTestButton, WhyDisabled } from "@/components/kb/probe-test-button";
import { UnverifiedSaveDialog } from "@/components/kb/unverified-save-dialog";
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
import { useProbeGate } from "@/hooks/use-probe-gate";
import { getErrorMessage, submitFailure } from "@/lib/api-error";
import {
  estimateKbProbe,
  probeKbEmbedding,
  type KbEmbeddingProbeBody,
} from "@/lib/embedding-probe-api";
import { qk } from "@/lib/query-keys";
import { DIALOG_BODY, DIALOG_COLUMN, DIALOG_WIDE } from "@/lib/dialog-sizes";
import { cn } from "@/lib/utils";
import type { EmbeddingProviderInput, KnowledgeBase } from "@/types";
import { useTranslations } from "next-intl";

/** The widest vector the index can hold; the same bound the server measures a custom model against. */
const MAX_INDEXED_DIM = 4000;

/**
 * Moving a collection's embeddings to another provider, tested against the
 * chunks already stored.
 *
 * The model is drawn and not offered - except for a custom endpoint, which
 * serves whatever model it names and so takes the model as text. That is the
 * shape of this dialog:
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
 * the next request. What makes that true is the Test: a few stored chunks are
 * embedded again through the new settings and compared with the vectors already
 * in the index. Save waits for a Test of exactly the values in the form, or for a
 * confirmed save without one.
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
  const [baseUrl, setBaseUrl] = useState(kb.embedding_base_url ?? "");
  const [endpointId, setEndpointId] = useState<string | null>(kb.embedding_endpoint_id);
  const [customModel, setCustomModel] = useState(kb.embedding_model);
  const [isSaving, setIsSaving] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [errors, setErrors] = useState<Readonly<Record<string, string>>>({});

  // Reopening shows what the server holds, not what was abandoned last time -
  // and a save elsewhere must not leave a stale draft to be posted over it.
  // Both called unconditionally and combined after: `||` would skip the second.
  const opened = useChanged(open);
  const rowMoved = useChanged(kb);
  if (opened || rowMoved) {
    setProvider(kb.embedding_provider);
    setSecretId(kb.embedding_secret_id);
    setEndpointId(kb.embedding_endpoint_id);
    setBaseUrl(kb.embedding_base_url ?? "");
    setCustomModel(kb.embedding_model);
    setErrors({});
  }

  // Only providers that serve this collection's model at its recorded width. A
  // list of every provider would offer moves the server refuses, and the reason
  // it refuses them is not something a person should have to discover twice.
  // A custom endpoint serves any model, so it qualifies on the width alone: the
  // index holds vectors up to a fixed size, and the Test decides the rest.
  const usable = (models?.providers ?? []).filter(
    (entry) =>
      entry.models.some(
        (model) => model.model === kb.embedding_model && model.dim === kb.embedding_dim,
      ) ||
      (entry.any_model && kb.embedding_dim >= 1 && kb.embedding_dim <= MAX_INDEXED_DIM),
  );
  const custom = usable.find((entry) => entry.provider === provider)?.any_model === true;
  const typedModel = customModel.trim();
  // The model cannot follow a move, so an endpoint that lists its models and
  // leaves this one out is refused on save - said here, before it is.
  const { served, checking } = useEndpointEmbeddingModels(provider, baseUrl);
  const endpointLacksModel =
    !custom &&
    served?.source === "live" &&
    !served.models.some((entry) => entry.model === kb.embedding_model);
  const moved =
    provider !== kb.embedding_provider ||
    secretId !== kb.embedding_secret_id ||
    endpointId !== kb.embedding_endpoint_id ||
    baseUrl.trim() !== (kb.embedding_base_url ?? "") ||
    (custom && typedModel !== kb.embedding_model);

  // A custom move needs its endpoint and model before it can be tested or saved.
  const incomplete = custom && (typedModel === "" || endpointId === null);
  const gate = useProbeGate({
    provider,
    secretId,
    endpointId,
    baseUrl: baseUrl.trim(),
    model: custom ? typedModel : null,
  });
  // What the disabled Save says on hover; an unchanged form needs no reason.
  const saveBlockedBy =
    !moved || endpointLacksModel
      ? null
      : incomplete
        ? t("blockedMissingSettings")
        : gate.token === null
          ? t("blockedRunTest")
          : null;
  const { data: estimate, error: estimateError } = useQuery({
    queryKey: qk.kb.probeEstimate(kb.id),
    queryFn: () => estimateKbProbe(kb.id),
    enabled: open && moved,
  });

  const proposed = (): EmbeddingProviderInput => ({
    embedding_provider: provider,
    ...(baseUrl.trim() !== (kb.embedding_base_url ?? "")
      ? { embedding_base_url: provider === "openrouter" ? baseUrl.trim() || null : null }
      : {}),
    // Null means "leave the key alone" on a partial update. There is no
    // deployment-wide key to go back to, so a key is only ever replaced,
    // never cleared - and the same for the connection a keyless or custom provider is
    // reached at.
    ...(secretId === null ? {} : { embedding_secret_id: secretId }),
    ...(endpointId === null ? {} : { embedding_endpoint_id: endpointId }),
    ...(custom && typedModel !== kb.embedding_model ? { embedding_model: typedModel } : {}),
  });

  const fail = (error: unknown) => {
    const failure = submitFailure(
      error,
      {
        fields: [
          "embedding_provider",
          "embedding_model",
          "embedding_secret_id",
          "embedding_endpoint_id",
          "embedding_base_url",
          "probe_token",
        ],
      },
      tErrors,
    );
    setErrors(failure.fields);
    if (failure.toast) toast.error(failure.toast);
  };

  const runTest = async () => {
    setErrors({});
    const body: KbEmbeddingProbeBody = proposed();
    try {
      await gate.test(() => probeKbEmbedding(kb.id, body));
    } catch (error) {
      fail(error);
    }
  };

  const save = async (extra: Pick<EmbeddingProviderInput, "probe_token" | "unverified">) => {
    setIsSaving(true);
    try {
      await onSave({ ...proposed(), ...extra });
      onOpenChange(false);
    } catch (error) {
      fail(error);
    } finally {
      setIsSaving(false);
    }
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!isSaving) onOpenChange(next);
      }}
    >
      <DialogContent dismissible={!isSaving} className={cn(DIALOG_COLUMN, DIALOG_WIDE)}>
        <DialogHeader>
          <DialogTitle>{t("embeddings")}</DialogTitle>
          <DialogDescription>{t("providerMoveKeepsTheIndex")}</DialogDescription>
        </DialogHeader>
        {/* Keep scrolling on the flex child; the fieldset retains its intrinsic height. */}
        <div className={cn(DIALOG_BODY, "scrollbar-thin")}>
          <fieldset disabled={isSaving} className="min-w-0 space-y-4">
            <legend className="sr-only">{t("embeddings")}</legend>
            <div className="border-border space-y-1 rounded-lg border p-3">
              <p className="text-muted-foreground text-xs">
                {t(custom ? "modelTestedAgainstStored" : "modelIsFixed")}
              </p>
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
                  endpointId={endpointId}
                  baseUrl={baseUrl}
                  onBaseUrl={setBaseUrl}
                  onProvider={setProvider}
                  onSecretId={setSecretId}
                  onEndpointId={setEndpointId}
                  model={customModel}
                  onModel={setCustomModel}
                  allowFreeModel
                  idPrefix="kb-embedding"
                />
                {endpointLacksModel && (
                  <p className="text-destructive text-xs">
                    {t("endpointLacksCollectionModel", { model: kb.embedding_model })}
                  </p>
                )}
                {(errors.embedding_provider ??
                  errors.embedding_model ??
                  errors.embedding_secret_id ??
                  errors.embedding_endpoint_id ??
                  errors.embedding_base_url ??
                  errors.probe_token) !== undefined && (
                  <p className="text-destructive text-xs">
                    {errors.embedding_provider ??
                      errors.embedding_model ??
                      errors.embedding_secret_id ??
                      errors.embedding_endpoint_id ??
                      errors.embedding_base_url ??
                      errors.probe_token}
                  </p>
                )}
                {moved && (
                  <div className="space-y-2">
                    <p className="text-muted-foreground text-xs">{t("testRetryNote")}</p>
                    {gate.result && <ProbeResult result={gate.result} />}
                    {gate.status === "failed" && (
                      <p className="text-muted-foreground text-xs">{t("probeFailedAdvice")}</p>
                    )}
                  </div>
                )}
              </>
            )}
          </fieldset>
        </div>
        <DialogFooter>
          {moved && (
            <div className="mr-auto flex flex-wrap items-center gap-2">
              <ProbeTestButton
                status={gate.status}
                disabled={
                  isSaving || checking || endpointLacksModel || estimate === undefined || incomplete
                }
                onClick={runTest}
              />
              {estimate ? (
                <span className="text-muted-foreground text-xs">
                  {t("testCost", { count: estimate.calls })}
                </span>
              ) : estimateError ? (
                <span className="text-destructive text-xs">
                  {getErrorMessage(estimateError, tErrors, t("testCostUnavailable"))}
                </span>
              ) : null}
            </div>
          )}
          <Button
            type="button"
            variant="outline"
            disabled={isSaving}
            onClick={() => onOpenChange(false)}
          >
            {t("cancel")}
          </Button>
          {moved && (
            <Button
              type="button"
              variant="ghost"
              disabled={isSaving || checking || endpointLacksModel || incomplete}
              onClick={() => setConfirming(true)}
            >
              {t("saveWithoutTest")}
            </Button>
          )}
          <WhyDisabled reason={isSaving || checking ? null : saveBlockedBy}>
            <Button
              type="button"
              onClick={() => save(gate.token === null ? {} : { probe_token: gate.token })}
              disabled={!moved || isSaving || checking || endpointLacksModel || gate.token === null}
            >
              {isSaving ? t("saving") : t("save")}
            </Button>
          </WhyDisabled>
        </DialogFooter>
        <UnverifiedSaveDialog
          open={confirming}
          onOpenChange={setConfirming}
          affected={estimate?.knowledge_bases ?? 1}
          onConfirm={() => {
            setConfirming(false);
            void save({ unverified: true });
          }}
        />
      </DialogContent>
    </Dialog>
  );
}
