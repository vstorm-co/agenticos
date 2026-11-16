"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Input } from "@/components/ui/input";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import { ProviderIcon } from "@/components/vault/provider-icon";
import { useSecrets } from "@/hooks/use-secrets";
import type { ModelProfile, ProviderInfo } from "@/types/providers";
import { cn } from "@/lib/utils";
import { ChatModelOptions } from "./chat-model-options";

interface Props {
  profiles: ModelProfile[];
  catalog: ProviderInfo[];
  value: string | null;
  currentProvider: string | undefined;
  onChange: (profileId: string) => void;
}

// A null secret can mean a native subscription, a keyless endpoint or a removed
// credential. Keep those connections separate; never infer availability from it.
const accountId = (profile: ModelProfile) =>
  profile.secret_id ??
  (profile.usage_scope === "personal" ? "personal" : (profile.base_url ?? profile.id));

/** Mounted only for a caller who holds the existing connections:manage gate. */
export function ChatModelMenu({ profiles, catalog, value, currentProvider, onChange }: Props) {
  const t = useTranslations("chat.modelSelector");
  const { secrets } = useSecrets();
  const providers = [...new Set(profiles.map((profile) => profile.provider))];
  const [selectedProvider, setProvider] = useState(currentProvider);
  const provider = providers.includes(selectedProvider ?? "") ? selectedProvider : providers[0];
  const [query, setQuery] = useState("");
  const [selectedAccount, setAccount] = useState("all");
  const providerModels = profiles.filter((profile) => profile.provider === provider);
  const accounts = [
    ...new Map(providerModels.map((profile) => [accountId(profile), profile])).entries(),
  ];
  const account = accounts.some(([id]) => id === selectedAccount) ? selectedAccount : "all";
  const providerName = (id: string) => catalog.find((item) => item.id === id)?.name ?? id;
  const accountName = (profile: ModelProfile) =>
    secrets.find((secret) => secret.id === profile.secret_id)?.name ??
    (profile.usage_scope === "personal" ? t("personalAccount") : profile.label);
  const needle = query.trim().toLocaleLowerCase();
  const matches = providerModels.filter(
    (profile) =>
      (account === "all" || accountId(profile) === account) &&
      [profile.label, profile.model, accountName(profile), profile.base_url ?? ""]
        .join(" ")
        .toLocaleLowerCase()
        .includes(needle),
  );

  return (
    <div className="flex min-h-48">
      <div
        role="group"
        aria-label={t("providers")}
        className="bg-muted/30 flex w-14 shrink-0 flex-col gap-1 border-r p-1.5"
      >
        {providers.map((id) => (
          <button
            key={id}
            type="button"
            aria-label={providerName(id)}
            aria-pressed={id === provider}
            title={providerName(id)}
            onClick={() => {
              setProvider(id);
              setAccount("all");
              setQuery("");
            }}
            className={cn(
              "flex size-10 shrink-0 items-center justify-center rounded-lg",
              id === provider
                ? "bg-accent text-foreground"
                : "text-muted-foreground hover:bg-accent/60",
            )}
          >
            <ProviderIcon provider={id} className="size-5" />
          </button>
        ))}
      </div>
      <div className="min-w-0 flex-1 space-y-2 p-3">
        {provider && <p className="text-xs font-medium">{providerName(provider)}</p>}
        <Input
          aria-label={t("search")}
          placeholder={t("search")}
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          className="h-8 text-xs"
        />
        {accounts.length > 1 && (
          <Select value={account} onValueChange={setAccount}>
            <SelectTrigger aria-label={t("account")} className="h-8 text-xs">
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">{t("allAccounts")}</SelectItem>
              {accounts.map(([id, profile]) => (
                <SelectItem key={id} value={id}>
                  {accountName(profile)}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        )}
        <ChatModelOptions
          profiles={matches}
          value={value}
          accountName={accountName}
          onChange={onChange}
        />
        {matches.length === 0 && (
          <p role="status" className="text-muted-foreground px-2 py-4 text-xs">
            {profiles.length === 0 ? t("empty") : t("noMatches")}
          </p>
        )}
        <p className="text-muted-foreground border-t pt-3 text-[11px] leading-relaxed">
          {t("advancedHint")}
        </p>
      </div>
    </div>
  );
}
