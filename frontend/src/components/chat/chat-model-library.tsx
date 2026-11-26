"use client";

import { useId, useState, useRef, useLayoutEffect, type ReactNode } from "react";
import { Command } from "cmdk";
import { Check, KeyRound, RefreshCw, Search } from "lucide-react";
import { useTranslations } from "next-intl";
import { ModelIcon } from "@/components/icons/model-icon";
import { ProviderRow } from "@/components/vault/provider-row";
import {
  Button,
  Skeleton,
  Spinner,
  Tabs,
  TabsList,
  TabsTrigger,
  TabsContent,
} from "@/components/ui";
import { COMMAND_ITEM_FOCUS, CONTROL_FOCUS } from "@/components/ui/control-styles";
import type { ProviderModel } from "@/hooks/use-model-providers";
import type { ModelProfile } from "@/types/providers";
import { modelIdIsWellFormed } from "@/components/agents/add-model";
import { catalogModelName, modelName } from "@/lib/model-profiles";
import { subscriptionFromChoice } from "@/lib/subscription-accounts-api";
import { cn } from "@/lib/utils";

interface LibraryProvider {
  id: string;
  label: string;
  connected: boolean | null;
  group?: "subscriptions" | "organization" | "custom";
  mark?: string;
}
export interface ChatModelLibraryProps {
  pane?: ReactNode;
  credentialTabLabel?: string;
  connectionLabel?: string;
  allowCustom?: boolean;
  providers: LibraryProvider[];
  providerId: string;
  model: string;
  models: ProviderModel[];
  profiles: ModelProfile[];
  catalogProfiles?: ModelProfile[];
  loading: boolean;
  catalogRefreshing?: boolean;
  catalogSource?: "live" | "curated" | "unlisted" | null;
  catalogError?: boolean;
  onRefresh?: () => void;
  catalogConnection?: ReactNode;
  loadingProviders?: boolean;
  needsCredential?: boolean;
  credentialPicker?: ReactNode;
  applying: boolean;
  disabled: boolean;
  onProviderChange: (id: string) => void;
  onModelChange: (model: string) => void;
  credentialForm: ReactNode;
  /** An endpoint-required provider uses the shared connection/model form before creation. */
  configurationForm?: ReactNode;
  failure: ReactNode;
}

/** Provider navigation stays mounted while each source owns its selection state. */
export function ChatModelLibrary(props: ChatModelLibraryProps) {
  const t = useTranslations("chat.modelPicker");
  const sources = useTranslations("modelSources");
  const sorted = [...props.providers].sort(
    (a, b) => Number(b.connected) - Number(a.connected) || a.label.localeCompare(b.label),
  );
  const selectedProvider = useRef<HTMLButtonElement>(null);
  const providerOrder = sorted.map((entry) => entry.id).join("|");
  useLayoutEffect(() => {
    selectedProvider.current?.scrollIntoView({ block: "nearest", behavior: "instant" });
  }, [props.providerId, props.loadingProviders, providerOrder]);
  const inGroup = (entry: LibraryProvider, group: string | boolean | null) =>
    group === "subscriptions" || group === "custom"
      ? entry.group === group
      : entry.group !== "subscriptions" && entry.group !== "custom" && entry.connected === group;
  return (
    <div
      className="grid h-[440px] min-h-0 flex-1 grid-cols-[minmax(112px,32%)_minmax(0,1fr)] grid-rows-[minmax(0,1fr)] sm:grid-cols-[196px_minmax(0,1fr)]"
      data-chat-model-library
    >
      <div
        role="group"
        aria-label={t("provider")}
        className="border-border bg-muted/20 min-h-0 scrollbar-thin overflow-y-auto overscroll-contain border-r p-1.5"
      >
        {props.loadingProviders ? (
          <div className="space-y-2 p-2" role="status">
            <span className="sr-only">{t("provider")}</span>
            {Array.from({ length: 5 }, (_, index) => (
              <Skeleton key={index} className="h-9 w-full rounded-lg" />
            ))}
          </div>
        ) : (
          ["subscriptions", true, false, null, "custom"]
            .filter((group) => sorted.some((entry) => inGroup(entry, group)))
            .map((connected) => (
              <div key={String(connected)} className="mb-3">
                <p className="text-muted-foreground px-2 py-2 text-[10px] font-medium">
                  {connected === "subscriptions" || connected === "custom"
                    ? sources(connected)
                    : t(
                        connected === null
                          ? "provider"
                          : connected
                            ? "connectedProviders"
                            : "providersWithoutKey",
                      )}
                </p>
                {sorted
                  .filter((entry) => inGroup(entry, connected))
                  .map((entry) => (
                    <button
                      key={entry.id}
                      type="button"
                      ref={props.providerId === entry.id ? selectedProvider : undefined}
                      aria-pressed={props.providerId === entry.id}
                      onClick={() => {
                        props.onProviderChange(entry.id);
                      }}
                      className={cn(
                        CONTROL_FOCUS,
                        "touch:min-h-11 flex min-h-10 w-full items-center gap-2 rounded-lg px-2 py-2 text-left text-xs",
                        props.providerId === entry.id
                          ? "bg-control-active font-medium [scroll-initial-target:nearest]"
                          : "text-muted-foreground hover:bg-muted/70",
                      )}
                    >
                      <ProviderRow
                        wrap
                        provider={entry.mark ?? entry.id}
                        name={entry.label.charAt(0).toLocaleUpperCase() + entry.label.slice(1)}
                      />
                      {entry.group === "subscriptions" && entry.connected === true && (
                        <Check className="text-success ml-auto size-3 shrink-0" aria-hidden />
                      )}
                      {connected === false && (
                        <KeyRound className="ml-auto size-3 shrink-0 opacity-50" aria-hidden />
                      )}
                    </button>
                  ))}
              </div>
            ))
        )}
      </div>
      {props.pane ?? <ChatModelPane key={props.providerId} {...props} />}
    </div>
  );
}

export type ChatModelPaneProps = Omit<
  ChatModelLibraryProps,
  "providers" | "loadingProviders" | "onProviderChange" | "pane"
>;

/** The same searchable model list is used for API keys and subscription accounts. */
export function ChatModelPane(props: ChatModelPaneProps) {
  const t = useTranslations("chat.modelPicker");
  const vault = useTranslations("vault");
  const [query, setQuery] = useState("");
  const [searchExpanded, setSearchExpanded] = useState(false);
  const searchButton = useRef<HTMLButtonElement>(null);
  const searchInput = useRef<HTMLInputElement>(null);
  const searchId = useId();
  const infoId = useId();
  const [tab, setTab] = useState("catalog");
  const hasCredentials = Boolean(props.credentialPicker || props.credentialForm);
  const activeTab = tab === "key" && !hasCredentials ? "catalog" : tab;
  useLayoutEffect(() => {
    if (searchExpanded && activeTab === "catalog") searchInput.current?.focus();
  }, [searchExpanded, activeTab]);
  const closeSearch = () => {
    setSearchExpanded(false);
    setQuery("");
    searchButton.current?.focus();
  };
  const needle = query.trim().toLowerCase();
  const profileProvider = subscriptionFromChoice(props.providerId)
    ? "subscription_accounts"
    : props.providerId;
  const profiles = props.profiles.filter((entry) => entry.provider === profileProvider);
  const matches = (model: string, label: string) =>
    `${model} ${label}`.toLowerCase().includes(needle);
  const catalog = new Map(props.models.map((entry) => [entry.id, entry]));
  for (const profile of props.catalogProfiles ?? profiles) {
    if (!catalog.has(profile.model)) {
      catalog.set(profile.model, {
        id: profile.model,
        name: modelName(profile),
        context_length: profile.context_length,
      });
    }
  }
  const modelRows = [...catalog.values()]
    .filter((entry) => matches(entry.id, entry.name))
    .sort((a, b) => Number(b.id === props.model) - Number(a.id === props.model));
  const catalogSource = props.catalogSource
    ? t(
        props.catalogSource === "live"
          ? "catalogLive"
          : props.catalogSource === "curated"
            ? "catalogFallback"
            : "catalogUnlisted",
      )
    : "";
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
        (activeTab === "catalog" && (props.loading || props.catalogRefreshing))
      }
      key={id}
      value={id}
      onSelect={onSelect}
      className={cn(
        COMMAND_ITEM_FOCUS,
        "flex min-h-10 cursor-pointer items-center gap-2.5 rounded-lg px-2.5 py-1.5",
      )}
    >
      <ModelIcon model={model} provider={props.providerId} />
      <span className="min-w-0 flex-1 truncate text-[13px] font-medium">{label}</span>
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
    <div className="flex min-h-0 min-w-0 flex-col">
      {props.needsCredential ? (
        <div className="min-h-0 flex-1 scrollbar-thin overflow-y-auto overscroll-contain p-4 [&>div]:justify-center">
          {props.credentialForm}
        </div>
      ) : (
        <Tabs value={activeTab} onValueChange={setTab} className="flex min-h-0 flex-1 flex-col">
          <div
            className="border-border flex shrink-0 items-center gap-1 border-b pr-2"
            data-model-toolbar
          >
            <TabsList className="min-w-0 flex-1 border-0 px-2 shadow-none" aria-label={t("model")}>
              <TabsTrigger value="catalog" aria-describedby={infoId}>
                {t("allModels")}
              </TabsTrigger>
              {hasCredentials && (
                <TabsTrigger value="key" title={props.connectionLabel}>
                  {props.credentialTabLabel ?? vault("key")}
                </TabsTrigger>
              )}
            </TabsList>
            <span id={infoId} className="sr-only">
              {t("catalogCount", { count: modelRows.length })}
              {catalogSource && ` · ${catalogSource}`}
            </span>
            {activeTab === "catalog" && !props.configurationForm && (
              <div className="flex shrink-0 items-center gap-0.5">
                {!props.loading && (
                  <span
                    aria-hidden
                    className="text-muted-foreground mr-1 hidden text-[10px] sm:inline"
                    title={catalogSource}
                  >
                    {t("catalogCount", { count: modelRows.length })}
                  </span>
                )}
                <Button
                  ref={searchButton}
                  type="button"
                  size="icon-sm"
                  variant="ghost"
                  aria-label={t("searchModels")}
                  aria-expanded={searchExpanded}
                  aria-controls={searchId}
                  onClick={() => (searchExpanded ? closeSearch() : setSearchExpanded(true))}
                >
                  <Search aria-hidden className="size-3.5" />
                </Button>
                {props.onRefresh && (
                  <Button
                    type="button"
                    size="icon-sm"
                    variant="ghost"
                    aria-label={t("refreshCatalog")}
                    disabled={props.loading || props.catalogRefreshing}
                    onClick={props.onRefresh}
                  >
                    <RefreshCw
                      aria-hidden
                      className={cn(
                        "size-3.5",
                        props.catalogRefreshing && "animate-spin motion-reduce:animate-none",
                      )}
                    />
                  </Button>
                )}
              </div>
            )}
          </div>
          {props.catalogError && (
            <p role="alert" className="text-destructive shrink-0 px-3 py-2 text-xs">
              {t("catalogFailed")}
            </p>
          )}
          <TabsContent value="key" className="mt-0 flex min-h-0 flex-1 flex-col">
            <div className="min-h-0 flex-1 scrollbar-thin space-y-3 overflow-y-auto overscroll-contain p-3">
              {props.credentialPicker}
              {props.credentialForm}
            </div>
          </TabsContent>
          <TabsContent
            value="catalog"
            key={activeTab}
            className="mt-0 flex min-h-0 flex-1 flex-col"
          >
            {activeTab === "catalog" && props.configurationForm ? (
              <div className="min-h-0 flex-1 scrollbar-thin overflow-y-auto overscroll-contain p-3">
                {props.configurationForm}
              </div>
            ) : (
              <div className="flex min-h-0 min-w-0 flex-1 flex-col">
                {activeTab === "catalog" && props.catalogConnection && (
                  <div className="border-border shrink-0 border-b px-3 py-3">
                    {props.catalogConnection}
                  </div>
                )}
                <Command shouldFilter={false} loop className="flex min-h-0 flex-1 flex-col">
                  <div
                    id={searchId}
                    data-model-search
                    hidden={!searchExpanded}
                    className={
                      searchExpanded
                        ? "border-border flex shrink-0 items-center gap-2 border-b px-3 py-2"
                        : "hidden"
                    }
                  >
                    <Search className="text-muted-foreground size-3.5 shrink-0" aria-hidden />
                    <Command.Input
                      ref={searchInput}
                      value={query}
                      onValueChange={setQuery}
                      placeholder={t("searchModels")}
                      aria-label={t("searchModels")}
                      onKeyDown={(event) => {
                        if (event.key === "Escape") {
                          event.preventDefault();
                          event.stopPropagation();
                          closeSearch();
                        }
                      }}
                      className="h-7 min-w-0 flex-1 bg-transparent text-xs outline-none"
                    />
                  </div>
                  <Command.List className="min-h-0 flex-1 scrollbar-thin overflow-y-auto overscroll-contain p-1.5">
                    {activeTab === "catalog" && props.loading && (
                      <div role="status" className="space-y-2 p-2">
                        <span className="sr-only">{t("loadingModels")}</span>
                        {Array.from({ length: 5 }, (_, index) => (
                          <Skeleton key={index} className="h-10 w-full rounded-lg" />
                        ))}
                      </div>
                    )}
                    {!props.loading && (
                      <Command.Empty className="text-muted-foreground px-3 py-5 text-xs">
                        {t(query.trim() ? "noMatchingModels" : "searchOrType")}
                      </Command.Empty>
                    )}
                    {activeTab === "catalog" &&
                      modelRows.map((entry) =>
                        row(
                          entry.id,
                          entry.id,
                          catalogModelName(entry.id, entry.name),
                          props.model === entry.id,
                          () => props.onModelChange(entry.id),
                          entry.context_length,
                        ),
                      )}
                    {activeTab === "catalog" &&
                      props.allowCustom !== false &&
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
              </div>
            )}
          </TabsContent>
        </Tabs>
      )}
      {(props.failure || props.applying) && (
        <div className="border-border max-h-24 shrink-0 scrollbar-thin space-y-3 overflow-y-auto overscroll-contain border-t p-3">
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
  );
}
