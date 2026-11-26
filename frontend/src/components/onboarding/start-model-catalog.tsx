"use client";

import { useState } from "react";
import { Command } from "cmdk";
import { Check, RefreshCw, Search } from "lucide-react";
import { useTranslations } from "next-intl";
import { ModelIcon } from "@/components/icons/model-icon";
import { Button, Skeleton } from "@/components/ui";
import type { ChatModelPaneProps } from "@/components/chat/chat-model-library";
import { modelIdIsWellFormed } from "@/components/agents/add-model";
import { catalogModelName, modelName } from "@/lib/model-profiles";
import styles from "./start-models.module.css";

/** A full-width catalog, after a provider and its account have been chosen. */
export function StartModelCatalog(props: ChatModelPaneProps) {
  const t = useTranslations("chat.modelPicker");
  const [query, setQuery] = useState("");
  const catalog = new Map(props.models.map((entry) => [entry.id, entry]));
  for (const profile of props.catalogProfiles ?? props.profiles) {
    if (!catalog.has(profile.model))
      catalog.set(profile.model, {
        id: profile.model,
        name: modelName(profile),
        context_length: profile.context_length,
      });
  }
  const needle = query.trim().toLocaleLowerCase();
  const models = [...catalog.values()].filter((entry) =>
    `${entry.id} ${entry.name}`.toLocaleLowerCase().includes(needle),
  );
  const busy = props.disabled || props.loading || props.catalogRefreshing || props.applying;
  const custom =
    props.allowCustom !== false &&
    query.trim() &&
    !catalog.has(query.trim()) &&
    modelIdIsWellFormed(props.providerId, query.trim());
  return (
    <div className={styles.catalog}>
      <Command shouldFilter={false} loop>
        <div className={styles.catalogToolbar} data-start-catalog-toolbar>
          <div className={styles.search}>
            <Search aria-hidden className="text-muted-foreground size-4" />
            <Command.Input
              value={query}
              onValueChange={setQuery}
              placeholder={t("searchModels")}
              aria-label={t("searchModels")}
              autoComplete="off"
              autoCapitalize="none"
              spellCheck={false}
            />
          </div>
          {props.catalogConnection && (
            <div className={styles.catalogConnection}>{props.catalogConnection}</div>
          )}
          <div className={styles.catalogFooter}>
            <div>
              {!props.loading && <p>{t("catalogCount", { count: models.length })}</p>}
              {props.catalogError ? (
                <p role="alert" className="text-destructive">
                  {t("catalogFailed")}
                </p>
              ) : (
                props.catalogSource && (
                  <p>
                    {t(
                      props.catalogSource === "live"
                        ? "catalogLive"
                        : props.catalogSource === "curated"
                          ? "catalogFallback"
                          : "catalogUnlisted",
                    )}
                  </p>
                )
              )}
            </div>
            {props.onRefresh && (
              <Button
                type="button"
                variant="ghost"
                size="icon"
                aria-label={t("refreshCatalog")}
                disabled={props.loading || props.catalogRefreshing}
                onClick={props.onRefresh}
              >
                <RefreshCw aria-hidden className="size-4" />
              </Button>
            )}
          </div>
        </div>
        <Command.List className={styles.modelList}>
          {props.loading ? (
            <div role="status" aria-label={t("loadingModels")} className="grid gap-2 p-2">
              {Array.from({ length: 4 }, (_, index) => (
                <Skeleton key={index} className="h-12 rounded-lg" />
              ))}
            </div>
          ) : (
            <>
              <Command.Empty className={styles.empty}>
                {t(query.trim() ? "noMatchingModels" : "searchOrType")}
              </Command.Empty>
              {models.map((entry) => (
                <Command.Item
                  key={entry.id}
                  value={entry.id}
                  disabled={busy}
                  onSelect={() => props.onModelChange(entry.id)}
                  className={styles.model}
                >
                  <ModelIcon model={entry.id} provider={props.providerId} />
                  <span>{catalogModelName(entry.id, entry.name)}</span>
                  {props.model === entry.id && (
                    <Check aria-label={t("selected")} className="size-4 shrink-0" />
                  )}
                </Command.Item>
              ))}
              {custom && (
                <Command.Item
                  value={`custom:${query.trim()}`}
                  disabled={busy}
                  onSelect={() => props.onModelChange(query.trim())}
                  className={styles.model}
                >
                  {t("customModel", { model: query.trim() })}
                </Command.Item>
              )}
            </>
          )}
        </Command.List>
      </Command>
    </div>
  );
}
