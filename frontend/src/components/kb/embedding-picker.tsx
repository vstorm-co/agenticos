"use client";

import { useQuery } from "@tanstack/react-query";

import { InlineLocalService } from "@/components/kb/inline-local-service";
import { InlineSecret } from "@/components/vault/inline-secret";
import { ProviderRow } from "@/components/vault/provider-row";
import {
  Input,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  useDebounced,
} from "@/components/ui";
import { useLocalServices, usePermissions, useSecrets } from "@/hooks";
import { Perm } from "@/types/permissions";
import { apiClient } from "@/lib/api-client";
import type { EmbeddingModels, EndpointEmbeddingModels } from "@/types";
import { useTranslations } from "next-intl";

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
 * The embedding models a custom OpenRouter endpoint serves, once one is typed.
 *
 * A regional endpoint serves a subset of the catalog - OpenRouter's EU one has
 * none of OpenAI's models - and a collection on a model its endpoint does not
 * serve fails every upload. So the create form offers what the endpoint lists.
 * Asked only by somebody who may set an endpoint, which the route requires, and
 * debounced so typing an address is not a request per keystroke.
 *
 * `served` is undefined while there is nothing to ask or no answer yet; the
 * caller then offers the provider's catalog, which is what the global address
 * serves. `checking` is true from the first keystroke until the answer for the
 * address now in the field arrives, and a form saving an endpoint waits on it.
 */
export function useEndpointEmbeddingModels(provider: string, baseUrl: string) {
  const { can } = usePermissions();
  const typed = baseUrl.trim().replace(/\/+$/, "");
  const url = useDebounced(typed);
  const mayAsk = provider === "openrouter" && can(Perm.connectionsManage);
  const asks = mayAsk && url !== "";
  const { data, isFetching } = useQuery({
    queryKey: ["rag", "embedding-models", provider, url],
    queryFn: () =>
      apiClient.get<EndpointEmbeddingModels>(
        `/rag/embedding-models/${provider}?base_url=${encodeURIComponent(url)}`,
      ),
    enabled: asks,
    staleTime: 60 * 60 * 1000,
    // A half-typed address is refused, and the next keystroke asks again.
    retry: false,
  });
  // Still settling counts as checking, so a form cannot save the address it is
  // about to warn about: the debounce has not caught up, or the answer is in flight.
  const checking = mayAsk && typed !== "" && (typed !== url || isFetching);
  return { served: asks && typed === url ? data : undefined, checking };
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
 * another one. There is no deployment-wide key on offer: every collection pays
 * with a vault key of its own, and the picker is empty until one is chosen.
 *
 * A keyless provider - an Ollama on the deployment's own network - asks a
 * different question: not whose key, but *which server*. It is drawn as a select
 * over the local services registered for that provider, the organization's own
 * and the deployment-wide ones, with the same way to add one in place.
 */
export function EmbeddingProviderFields({
  models,
  provider,
  secretId,
  endpointId,
  baseUrl,
  onBaseUrl,
  onProvider,
  onSecretId,
  onEndpointId,
  idPrefix,
}: {
  models: EmbeddingModels;
  provider: string;
  /** The chosen vault key, or null while none is. */
  secretId: string | null;
  /** The chosen local service for a keyless provider, or null while none is. */
  endpointId: string | null;
  baseUrl: string;
  onBaseUrl: (url: string) => void;
  onProvider: (provider: string) => void;
  onSecretId: (secretId: string | null) => void;
  onEndpointId: (endpointId: string | null) => void;
  /** So two of these on one screen do not share an input id. */
  idPrefix: string;
}) {
  const t = useTranslations("kb");
  const { secrets } = useSecrets();
  const { can } = usePermissions();
  const entry = models.providers.find((item) => item.provider === provider);
  const keyless = entry?.keyless === true;
  const { services } = useLocalServices(keyless);
  const keys = secrets.filter((secret) => secret.purpose === provider);
  const servers = services.filter(
    (service) => service.kind === "embedding" && service.provider === provider && service.is_active,
  );

  return (
    <>
      <div className="space-y-1.5">
        <Label htmlFor={`${idPrefix}-provider`}>{t("embeddingProvider")}</Label>
        <Select
          value={provider}
          onValueChange={(next) => {
            onProvider(next);
            // A key or a server chosen for the provider being left behind would
            // be sent to the new one's address, which is the failure this whole
            // field exists to prevent. Cleared rather than kept and refused on save.
            if (secretId !== null) onSecretId(null);
            if (endpointId !== null) onEndpointId(null);
            onBaseUrl("");
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
      {provider === "openrouter" && (can(Perm.connectionsManage) || baseUrl !== "") && (
        <div className="space-y-1.5">
          <Label htmlFor={`${idPrefix}-url`}>{t("embeddingEndpoint")}</Label>
          <Input
            id={`${idPrefix}-url`}
            type="url"
            disabled={!can(Perm.connectionsManage)}
            value={baseUrl}
            onChange={(event) => onBaseUrl(event.target.value)}
            placeholder="https://openrouter.ai/api/v1"
          />
          <p className="text-muted-foreground text-xs">{t("embeddingEndpointHint")}</p>
        </div>
      )}
      {keyless ? (
        <div className="space-y-1.5">
          <Label htmlFor={`${idPrefix}-server`}>{t("server")}</Label>
          <Select value={endpointId ?? ""} onValueChange={onEndpointId}>
            <SelectTrigger id={`${idPrefix}-server`}>
              <SelectValue placeholder={t("chooseServer")} />
            </SelectTrigger>
            <SelectContent>
              {servers.map((service) => (
                <SelectItem key={service.id} value={service.id} textValue={service.name}>
                  <ProviderRow
                    provider={provider}
                    name={
                      service.organization_id === null
                        ? t("deploymentWideNamed", { name: service.name })
                        : service.name
                    }
                  />
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <p className="text-muted-foreground text-xs">
            {t("keylessProvider", { provider: entry.name })}
          </p>
          <InlineLocalService kind="embedding" provider={provider} onCreated={onEndpointId} />
        </div>
      ) : (
        <div className="space-y-1.5">
          <Label htmlFor={`${idPrefix}-key`}>{t("key")}</Label>
          {/* Controlled throughout: an empty string is how Radix is told "nothing
            chosen, show the placeholder", where `undefined` would flip the
            select to uncontrolled and leave the last key on the trigger. */}
          <Select value={secretId ?? ""} onValueChange={onSecretId}>
            <SelectTrigger id={`${idPrefix}-key`}>
              <SelectValue placeholder={t("chooseKey")} />
            </SelectTrigger>
            <SelectContent>
              {keys.map((secret) => (
                <SelectItem key={secret.id} value={secret.id} textValue={secret.name}>
                  <ProviderRow provider={provider} name={secret.name} hint={secret.hint} />
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <p className="text-muted-foreground text-xs">{t("keyRequiredHere")}</p>
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
      )}
    </>
  );
}
