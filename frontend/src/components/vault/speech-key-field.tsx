"use client";

import { useEffect } from "react";
import { ExternalLink, TriangleAlert } from "lucide-react";
import { useTranslations } from "next-intl";

import {
  FormField,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { InlineSecret } from "@/components/vault/inline-secret";
import { useSecrets } from "@/hooks";
import { ROUTES } from "@/lib/constants";
import type { Secret } from "@/types/secrets";

/**
 * The vault kinds a key on this field may be: an opaque API key for every
 * speech-to-text provider, and the Azure OpenAI shape (endpoint, deployment,
 * version) for a voice conversation held on Azure (#54).
 */
export type SpeechKeyKind = "api_key" | "azure_openai";

/**
 * The vault keys a speech-to-text pair on `provider` may be sent with.
 *
 * An API key whose purpose is the provider - a key is never sent to a service
 * it was not issued by - and, where `orgVisibleOnly`, one the whole organization
 * can see: the organization's default and a channel bot's key are spent by the
 * platform for everybody, so a member's private key may not pay for them. An
 * agent's key may be any the person can see, because publishing lends it.
 */
export function speechKeysFor(
  secrets: readonly Secret[],
  provider: string,
  orgVisibleOnly: boolean,
  kind: SpeechKeyKind = "api_key",
): Secret[] {
  return secrets.filter(
    (secret) =>
      secret.kind === kind &&
      secret.purpose === provider &&
      (!orgVisibleOnly || secret.visibility === "org"),
  );
}

/**
 * Whether a provider has a key that may be chosen at this level, for marking a
 * provider dropdown's entries "no key yet".
 *
 * Answers `true` while the vault is unread or could not be read: neither is a
 * missing key, and an entry marked for a frame - or for somebody who may not
 * list the vault - would say something nobody was told.
 */
export function useSpeechKeyCheck(orgVisibleOnly: boolean): (provider: string) => boolean {
  const { secrets, isLoading, listError } = useSecrets();
  return (provider) =>
    isLoading || listError !== null || speechKeysFor(secrets, provider, orgVisibleOnly).length > 0;
}

interface SpeechKeyFieldProps {
  /** For the select's id; unique on the page. */
  id: string;
  provider: string;
  /** The provider as people read it - "OpenAI". */
  providerName: string;
  /** The stored key's id, or null while none is chosen. */
  value: string | null;
  onChange: (secretId: string) => void;
  /** Organization-wide keys only - the organization's default and a bot's. */
  orgVisibleOnly: boolean;
  disabled?: boolean;
  /** The server's refusal for this field. */
  error?: string;
  /** The vault kind a key must be; `api_key` unless the provider takes another shape. */
  kind?: SpeechKeyKind;
  /** What a key added from here is called; the speech-to-text name by default. */
  suggestedName?: string;
}

/**
 * Which vault key a speech-to-text pair is sent with (#1797).
 *
 * One field for every level that names a pair - the organization's Voice card,
 * an agent's Voice card and a channel bot's dialog - so the rule about which
 * keys may be chosen is written once. The key is always stored explicitly: when
 * exactly one fits and none is chosen it is picked here, through `onChange`,
 * rather than looked up when a recording arrives - with two keys for one
 * provider a lookup is a guess about who pays.
 *
 * A stored key that is no longer offered - deleted, or no longer one this level
 * may use - is said to be one, and the select waits for another. With none at
 * all, the way to add one is beside it, as in `EmbeddingProviderFields`.
 */
export function SpeechKeyField({
  id,
  provider,
  providerName,
  value,
  onChange,
  orgVisibleOnly,
  disabled,
  error,
  kind = "api_key",
  suggestedName,
}: SpeechKeyFieldProps) {
  const t = useTranslations("vault");
  const { secrets, isLoading, listError } = useSecrets();
  const keys = speechKeysFor(secrets, provider, orgVisibleOnly, kind);
  const only = keys.length === 1 ? keys[0]!.id : null;
  const restrictedKeys = orgVisibleOnly
    ? speechKeysFor(secrets, provider, false, kind).filter((key) => key.visibility !== "org")
    : [];
  const chatGPTSignIns =
    provider === "openai" && kind === "api_key" && keys.length === 0
      ? secrets.filter((key) => key.kind === "openai_codex" && key.purpose === "openai_codex")
      : [];

  // A prop callback rather than state of this component: the key belongs to
  // whoever stores the pair, and storing it is the point.
  useEffect(() => {
    if (value === null && only !== null && !disabled) onChange(only);
  }, [value, only, disabled, onChange]);

  if (listError !== null) {
    return (
      <FormField label={t("speechKey.label")} htmlFor={id} error={error} className="sm:col-span-2">
        <p id={id} className="text-muted-foreground text-xs">
          {t("speechKey.cannotList")}
        </p>
      </FormField>
    );
  }

  const stale = !isLoading && value !== null && !keys.some((key) => key.id === value);
  const description = orgVisibleOnly ? t("speechKey.orgHint") : t("speechKey.agentHint");

  return (
    <div className="space-y-2 sm:col-span-2" data-kind={kind}>
      <FormField label={t("speechKey.label")} htmlFor={id} description={description} error={error}>
        {/* Controlled throughout: an empty string is how Radix is told "nothing
            chosen, show the placeholder". A stale id shows the placeholder too. */}
        <Select
          value={stale || value === null ? "" : value}
          disabled={disabled}
          onValueChange={onChange}
        >
          <SelectTrigger id={id}>
            <SelectValue placeholder={t("speechKey.choose")} />
          </SelectTrigger>
          <SelectContent>
            {keys.map((key) => (
              <SelectItem key={key.id} value={key.id} textValue={key.name}>
                {t("speechKey.option", { name: key.name, hint: key.hint })}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
      </FormField>
      {stale && (
        <p className="text-warning flex gap-2 text-xs" role="note">
          <TriangleAlert className="mt-0.5 h-3.5 w-3.5 shrink-0" aria-hidden />
          {t("speechKey.stale")}
        </p>
      )}
      {!isLoading && (restrictedKeys.length > 0 || chatGPTSignIns.length > 0) && (
        <ul className="text-muted-foreground space-y-1 text-xs">
          {restrictedKeys.map((key) => (
            <li key={key.id}>{t("speechKey.notShared", { name: key.name })}</li>
          ))}
          {chatGPTSignIns.map((key) => (
            <li key={key.id}>{t("speechKey.chatGPTSignIn", { name: key.name })}</li>
          ))}
        </ul>
      )}
      {!isLoading &&
        keys.length === 0 &&
        restrictedKeys.length === 0 &&
        chatGPTSignIns.length === 0 && (
          <p className="text-muted-foreground text-xs">
            {kind !== "api_key"
              ? t("speechKey.noneInVault", { provider: providerName })
              : orgVisibleOnly
                ? t("speechKey.noneOrg", { provider: providerName })
                : t("speechKey.none", { provider: providerName })}
          </p>
        )}
      {kind === "api_key" ? (
        <InlineSecret
          kind="api_key"
          purpose={provider}
          suggestedName={suggestedName ?? t("speechKey.suggestedName", { provider: providerName })}
          onCreated={onChange}
          disabled={disabled}
        />
      ) : (
        // The inline form stores one opaque value; an Azure key is an endpoint,
        // a key and an API version, which only the vault's own form takes.
        <a
          href={ROUTES.VAULT}
          target="_blank"
          rel="noreferrer noopener"
          className="text-muted-foreground hover:text-foreground inline-flex items-center gap-1 text-xs underline underline-offset-4"
        >
          <ExternalLink className="h-3 w-3" aria-hidden />
          {t("openVault")}
        </a>
      )}
    </div>
  );
}
