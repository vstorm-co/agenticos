"use client";

import { useQuery } from "@tanstack/react-query";

import { InlineSecret } from "@/components/vault/inline-secret";
import { ProviderRow } from "@/components/vault/provider-row";
import {
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { useSecrets } from "@/hooks";
import { apiClient } from "@/lib/api-client";
import type { EmbeddingModels } from "@/types";
import { useTranslations } from "next-intl";

/** Sentinel for "the deployment's key" - a Select item may not be empty. */
export const DEPLOYMENT_KEY = "__deployment__";

/**
 * Which providers this build can embed through, and what each serves.
 *
 * A build property rather than tenant data, so it never goes stale while a
 * dialog is open. `isError` is read because the section has three states and
 * used to draw two: `staleTime` governs staleness, not failure, so the retry
 * count decides how long refused lasts - one retry, then settled in error for
 * the life of the dialog, refetched when it reopens.
 */
export function useEmbeddingProviders() {
  const { data, isError } = useQuery({
    queryKey: ["rag", "embedding-models"],
    queryFn: () => apiClient.get<EmbeddingModels>("/rag/embedding-models"),
    staleTime: Infinity,
  });
  return { models: data, unreadable: isError };
}

/**
 * Whose endpoint serves a collection's embedding model, and whose key pays.
 *
 * One component for the two places the question is asked - creating a
 * collection, and re-pointing one that exists - because the rule they have to
 * agree on is not obvious: a key is a key *for a provider*, so changing the
 * provider without changing the key produces a collection holding an OpenRouter
 * key and an OpenAI address, which the provider refuses after the key has
 * already reached it. So choosing a provider here clears a key that belongs to
 * another one, and the deployment's key is offered only where it applies.
 */
export function EmbeddingProviderFields({
  models,
  provider,
  secretId,
  onProvider,
  onSecretId,
  idPrefix,
}: {
  models: EmbeddingModels;
  provider: string;
  /** The chosen vault key, or null for the deployment's. */
  secretId: string | null;
  onProvider: (provider: string) => void;
  onSecretId: (secretId: string | null) => void;
  /** So two of these on one screen do not share an input id. */
  idPrefix: string;
}) {
  const t = useTranslations("kb");
  const { secrets } = useSecrets();
  const entry = models.providers.find((item) => item.provider === provider);
  const keys = secrets.filter((secret) => secret.purpose === provider);

  return (
    <>
      <div className="space-y-1.5">
        <Label htmlFor={`${idPrefix}-provider`}>{t("embeddingProvider")}</Label>
        <Select
          value={provider}
          onValueChange={(next) => {
            onProvider(next);
            // A key for the provider being left behind would be sent to the new
            // one's address, which is the failure this whole field exists to
            // prevent. Cleared rather than kept and refused on save.
            if (secretId !== null) onSecretId(null);
          }}
        >
          <SelectTrigger id={`${idPrefix}-provider`}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {models.providers.map((item) => (
              <SelectItem key={item.provider} value={item.provider} textValue={item.name}>
                <ProviderRow provider={item.provider} name={item.name} />
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </div>
      <div className="space-y-1.5">
        <Label htmlFor={`${idPrefix}-key`}>{t("key")}</Label>
        <Select
          value={secretId ?? DEPLOYMENT_KEY}
          onValueChange={(value) => onSecretId(value === DEPLOYMENT_KEY ? null : value)}
        >
          <SelectTrigger id={`${idPrefix}-key`}>
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            {/* Only where it applies. The deployment has one key and it belongs
                to one provider; offering it elsewhere offers a collection that
                cannot index its first document. */}
            {entry?.deployment_key === true && (
              <SelectItem value={DEPLOYMENT_KEY} textValue={t("deploymentKey")}>
                <ProviderRow provider={provider} name={t("deploymentKey")} />
              </SelectItem>
            )}
            {keys.map((secret) => (
              <SelectItem key={secret.id} value={secret.id} textValue={secret.name}>
                <ProviderRow provider={provider} name={secret.name} hint={secret.hint} />
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <p className="text-muted-foreground text-xs">
          {entry?.deployment_key === true ? t("keyHereBillsEmbeddings") : t("keyRequiredHere")}
        </p>
        {/* Rather than only telling somebody to go and add one: a picker with
            nothing in it and no way to fill it is a dead end, and the answer to
            "add a key in the vault" is a form, not a sentence. Unconditional
            because the permission is its own decision to make - it says who has
            to add the key rather than rendering a gap. */}
        <InlineSecret
          kind="api_key"
          purpose={provider}
          suggestedName={t("embeddingsKeyName", { provider: entry?.name ?? provider })}
          onCreated={onSecretId}
        />
      </div>
    </>
  );
}
