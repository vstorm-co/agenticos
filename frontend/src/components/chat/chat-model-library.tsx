"use client";

import { useState, type ReactNode } from "react";
import { Command } from "cmdk";
import { Check, KeyRound, Search } from "lucide-react";
import { useTranslations } from "next-intl";
import { ModelIcon } from "@/components/icons/model-icon";
import { ProviderRow } from "@/components/vault/provider-row";
import { Skeleton, Spinner, Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui";
import { COMMAND_ITEM_FOCUS, CONTROL_FOCUS } from "@/components/ui/control-styles";
import type { ProviderModel } from "@/hooks/use-model-providers";
import type { ModelProfile } from "@/types/providers";
import { modelIdIsWellFormed } from "@/components/agents/add-model";
import { modelDetail } from "@/lib/model-profiles";
import { cn } from "@/lib/utils";

interface LibraryProvider {
  id: string;
  label: string;
  connected: boolean | null;
}
interface ChatModelLibraryProps {
  providers: LibraryProvider[];
  providerId: string;
  model: string;
  profileId?: string;
  models: ProviderModel[];
  profiles: ModelProfile[];
  loading: boolean;
  catalogRefreshing?: boolean;
  loadingProviders?: boolean;
  needsCredential?: boolean;
  credentialPicker?: ReactNode;
  applying: boolean;
  disabled: boolean;
  onProviderChange: (id: string) => void;
  onModelChange: (model: string) => void;
  onProfileChange: (profile: ModelProfile) => void;
  credentialForm: ReactNode;
  failure: ReactNode;
}

/** Provider navigation and model selection share one panel, without nested pickers. */
export function ChatModelLibrary(props: ChatModelLibraryProps) {
  const t = useTranslations("chat.modelPicker");
  const [query, setQuery] = useState("");
  const [tab, setTab] = useState("catalog");
  const needle = query.trim().toLowerCase();
  const profiles = props.profiles.filter((entry) => entry.provider === props.providerId);
  const matches = (model: string, label: string) =>
    `${model} ${label}`.toLowerCase().includes(needle);
  const saved = profiles.filter((entry) => matches(entry.model, entry.label));
  const catalog = new Map(props.models.map((entry) => [entry.id, entry]));
  for (const profile of profiles) {
    if (!catalog.has(profile.model)) {
      catalog.set(profile.model, {
        id: profile.model,
        name: profile.model.split("/").at(-1) || profile.model,
        context_length: profile.context_length,
      });
    }
  }
  const modelRows = [...catalog.values()].filter((entry) => matches(entry.id, entry.name));
  const sorted = [...props.providers].sort(
    (a, b) => Number(b.connected) - Number(a.connected) || a.label.localeCompare(b.label),
  );
  const row = (
    id: string,
    model: string,
    label: string,
    selected: boolean,
    onSelect: () => void,
    context?: number | null,
  ) => (
    <Command.Item
      disabled={
        props.disabled ||
        props.applying ||
        (tab === "catalog" && (props.loading || props.catalogRefreshing))
      }
      key={id}
      value={id}
      onSelect={onSelect}
      className={cn(
        COMMAND_ITEM_FOCUS,
        "flex cursor-pointer items-center gap-2.5 rounded-xl px-2.5 py-2.5",
      )}
    >
      <ModelIcon model={model} provider={props.providerId} className="size-8" />
      <span className="min-w-0 flex-1">
        <span className="block truncate text-[13px] font-medium">{label}</span>
        <span className="text-muted-foreground mt-0.5 block truncate text-[11px]" title={model}>
          {model}
        </span>
      </span>
      {selected ? (
        <Check className="size-3.5 shrink-0" aria-label={t("selected")} />
      ) : context ? (
        <span className="text-muted-foreground shrink-0 text-[10px]">
          {context >= 1_000_000
            ? `${Math.round(context / 1_000_000)}M`
            : `${Math.round(context / 1000)}K`}
        </span>
      ) : null}
    </Command.Item>
  );
  return (
    <div
      className="grid min-h-64 grid-cols-[minmax(112px,32%)_minmax(0,1fr)] sm:grid-cols-[196px_minmax(0,1fr)]"
      data-chat-model-library
    >
      <div
        role="group"
        aria-label={t("provider")}
        className="border-border bg-muted/20 max-h-[440px] overflow-y-auto overscroll-contain border-r p-1.5"
      >
        {props.loadingProviders ? (
          <div className="space-y-2 p-2" role="status">
            <span className="sr-only">{t("provider")}</span>
            {Array.from({ length: 5 }, (_, index) => (
              <Skeleton key={index} className="h-9 w-full rounded-lg" />
            ))}
          </div>
        ) : (
          [true, false, null].map((connected) => (
            <div key={String(connected)} className="mb-3">
              {sorted.some((entry) => entry.connected === connected) && (
                <p className="text-muted-foreground px-2 py-2 text-[10px] font-medium">
                  {t(
                    connected === null
                      ? "provider"
                      : connected
                        ? "connectedProviders"
                        : "providersWithoutKey",
                  )}
                </p>
              )}
              {sorted
                .filter((entry) => entry.connected === connected)
                .map((entry) => (
                  <button
                    key={entry.id}
                    type="button"
                    aria-pressed={props.providerId === entry.id}
                    onClick={() => {
                      setQuery("");
                      props.onProviderChange(entry.id);
                    }}
                    className={cn(
                      CONTROL_FOCUS,
                      "touch:min-h-11 flex min-h-10 w-full items-center gap-2 rounded-lg px-2 py-2 text-left text-xs",
                      props.providerId === entry.id
                        ? "bg-control-active font-medium"
                        : "text-muted-foreground hover:bg-muted/70",
                    )}
                  >
                    <ProviderRow
                      wrap
                      provider={entry.id}
                      name={entry.label.charAt(0).toLocaleUpperCase() + entry.label.slice(1)}
                    />
                    {connected === false && (
                      <KeyRound className="ml-auto size-3 shrink-0 opacity-50" aria-hidden />
                    )}
                  </button>
                ))}
            </div>
          ))
        )}
      </div>
      <div className="flex min-w-0 flex-col self-start">
        {props.needsCredential ? (
          <div className="grid min-h-64 place-content-center p-4 [&>div]:justify-center">
            {props.credentialForm}
          </div>
        ) : (
          <Tabs value={tab} onValueChange={setTab}>
            <TabsList className="px-2" aria-label={t("model")}>
              <TabsTrigger value="catalog">{t("allModels")}</TabsTrigger>
              <TabsTrigger value="saved">{t("savedModels")}</TabsTrigger>
            </TabsList>
            {props.credentialPicker}
            <TabsContent value={tab} key={tab} className="mt-0">
              <Command shouldFilter={false} loop className="min-w-0 flex-1">
                <div className="border-border flex items-center gap-2 border-b px-3 py-2.5">
                  <Search className="text-muted-foreground size-3.5 shrink-0" aria-hidden />
                  <Command.Input
                    value={query}
                    onValueChange={setQuery}
                    placeholder={t("searchModels")}
                    aria-label={t("searchModels")}
                    className="h-7 min-w-0 flex-1 bg-transparent text-xs outline-none"
                  />
                </div>
                {tab === "catalog" && props.loading && (
                  <div role="status" className="space-y-2 p-2">
                    <span className="sr-only">{t("loadingModels")}</span>
                    {Array.from({ length: 5 }, (_, index) => (
                      <Skeleton key={index} className="h-12 w-full rounded-xl" />
                    ))}
                  </div>
                )}
                <Command.List className="max-h-[340px] overflow-y-auto overscroll-contain p-1.5">
                  {!props.loading && (
                    <Command.Empty className="text-muted-foreground px-3 py-5 text-xs">
                      {t(
                        query.trim()
                          ? "noMatchingModels"
                          : tab === "saved"
                            ? "noSavedModels"
                            : "searchOrType",
                      )}
                    </Command.Empty>
                  )}
                  {tab === "saved" && saved.length > 0 && (
                    <Command.Group
                      heading={t("savedModels")}
                      className="[&_[cmdk-group-heading]]:text-muted-foreground [&_[cmdk-group-heading]]:px-2 [&_[cmdk-group-heading]]:py-2 [&_[cmdk-group-heading]]:text-[10px]"
                    >
                      {saved.map((entry) =>
                        row(
                          entry.id,
                          entry.model,
                          modelDetail(entry) === null
                            ? props.models
                                .find((model) => model.id === entry.model)
                                ?.name.split(":")
                                .pop()
                                ?.trim() ||
                                entry.model.split("/").pop() ||
                                entry.model
                            : entry.label,
                          props.profileId === entry.id,
                          () => props.onProfileChange(entry),
                          entry.context_length,
                        ),
                      )}
                    </Command.Group>
                  )}
                  {tab === "catalog" &&
                    modelRows
                      .slice(0, 100)
                      .map((entry) =>
                        row(
                          entry.id,
                          entry.id,
                          entry.name.split(":").pop()?.trim() || entry.id,
                          props.model === entry.id,
                          () => props.onModelChange(entry.id),
                          entry.context_length,
                        ),
                      )}
                  {tab === "catalog" &&
                    query.trim() &&
                    modelIdIsWellFormed(props.providerId, query.trim()) &&
                    !catalog.has(query.trim()) && (
                      <Command.Item
                        disabled={
                          props.disabled ||
                          props.applying ||
                          props.loading ||
                          props.catalogRefreshing ||
                          !modelIdIsWellFormed(props.providerId, query.trim())
                        }
                        value={`custom:${query.trim()}`}
                        onSelect={() => props.onModelChange(query.trim())}
                        className={cn(
                          COMMAND_ITEM_FOCUS,
                          "cursor-pointer rounded-lg px-3 py-3 text-xs",
                        )}
                      >
                        {t("customModel", { model: query.trim() })}
                      </Command.Item>
                    )}
                </Command.List>
              </Command>
            </TabsContent>
          </Tabs>
        )}
        {((props.credentialForm && !props.needsCredential) || props.failure || props.applying) && (
          <div className="border-border space-y-3 border-t p-3">
            {!props.needsCredential && props.credentialForm}
            {props.failure}
            {props.applying && (
              <p role="status" className="text-muted-foreground flex items-center gap-2 text-xs">
                <Spinner className="size-3.5" />
                {t("applyingModel")}
              </p>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
