"use client";

import { useTranslations } from "next-intl";
import { Button, SearchInput, Skeleton } from "@/components/ui";
import { GOAL_TOOLKITS, type AppConnectionGoal } from "@/lib/app-connection-journey";
import type { AppConnection, ConnectedAppDefinition } from "@/types/app-connections";
import { ConnectionAppCard } from "./connection-app-card";

interface ConnectionCatalogProps {
  apps: ConnectedAppDefinition[];
  connections: AppConnection[];
  goal: AppConnectionGoal;
  requestedToolkit: string | null;
  busy: boolean;
  search: string;
  onSearch: (value: string) => void;
  loading: boolean;
  loadingMore: boolean;
  hasMore: boolean;
  catalogAvailable: boolean;
  error: string | null;
  onLoadMore: () => void;
  onRetry: () => void;
  onConnect: (app: ConnectedAppDefinition) => void;
}

export function ConnectionCatalog(props: ConnectionCatalogProps) {
  const t = useTranslations("appConnections");
  const preferred = props.requestedToolkit ? [props.requestedToolkit] : GOAL_TOOLKITS[props.goal];
  const apps = [...props.apps].sort(
    (a, b) => Number(preferred.includes(b.toolkit)) - Number(preferred.includes(a.toolkit)),
  );
  return (
    <section className="space-y-4" aria-label={t("catalogTitle")}>
      <div>
        <h2 className="text-lg font-medium" data-tour="app-connection-catalog">
          {t("catalogTitle")}
        </h2>
        <p className="text-muted-foreground mt-1 text-sm">{t("catalogHint")}</p>
      </div>
      <SearchInput
        value={props.search}
        onChange={props.onSearch}
        placeholder={t("searchApps")}
        maxLength={200}
        className="sm:w-full"
      />
      {props.error && (
        <div role="alert" className="space-y-2">
          <p className="text-destructive text-sm">{props.error}</p>
          <Button variant="outline" onClick={props.onRetry}>
            {t("retry")}
          </Button>
        </div>
      )}
      {!props.loading && !props.error && !props.catalogAvailable && (
        <div role="status" className="bg-muted space-y-2 rounded-lg p-3 text-sm">
          <p>{t("catalogUnavailable")}</p>
          <Button variant="outline" size="sm" onClick={props.onRetry}>
            {t("retry")}
          </Button>
        </div>
      )}
      {props.loading ? (
        <Skeleton className="h-48 rounded-xl" />
      ) : (
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {apps.map((app) => (
            <ConnectionAppCard
              key={app.key}
              app={app}
              recommended={preferred.includes(app.toolkit)}
              connected={props.connections.some((item) => item.toolkit === app.toolkit)}
              busy={props.busy}
              onConnect={props.onConnect}
            />
          ))}
        </div>
      )}
      {props.hasMore && (
        <Button variant="outline" loading={props.loadingMore} onClick={props.onLoadMore}>
          {t("loadMore")}
        </Button>
      )}
      {!props.loading && !props.error && apps.length === 0 && (
        <p role="status" className="text-muted-foreground text-sm">
          {t(props.search ? "noSearchResults" : "noApps")}
        </p>
      )}
    </section>
  );
}
