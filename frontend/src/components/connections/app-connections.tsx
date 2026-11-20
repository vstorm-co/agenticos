"use client";

import { useSearchParams } from "next/navigation";
import { useTranslations } from "next-intl";
import { ArrowRight, ShieldCheck } from "lucide-react";
import { Button, Skeleton } from "@/components/ui";
import { ErrorState } from "@/components/states";
import { getErrorMessage } from "@/lib/api-error";
import type { AppConnectionScope } from "@/types/app-connections";
import { ConnectionAccounts } from "./connection-accounts";
import { ConnectionAuthorizationDialog } from "./connection-authorization-dialog";
import { ConnectionCatalog } from "./connection-catalog";
import { ConnectionDisconnectDialog } from "./connection-disconnect-dialog";
import { ConnectionFirstTask } from "./connection-first-task";
import { ConnectionGoals } from "./connection-goals";
import { useConnectionJourney } from "./use-connection-journey";

export function AppConnections({ scope }: { scope: AppConnectionScope }) {
  const t = useTranslations("appConnections");
  const tErrors = useTranslations("errors");
  const search = useSearchParams();
  const journey = useConnectionJourney(scope);
  const apps = journey.catalog.data?.apps ?? [];
  const connections = journey.connections.data ?? [];
  const requestedToolkit = search.get("app");
  const error = journey.connections.error;
  if (journey.connections.isLoading) return <Skeleton className="h-64 rounded-xl" />;
  if (error)
    return (
      <div className="space-y-3">
        <ErrorState description={getErrorMessage(error, tErrors)} />
        <Button variant="outline" onClick={() => void journey.refresh()}>
          {t("retry")}
        </Button>
      </div>
    );
  return (
    <div className="space-y-6">
      <section className="bg-card space-y-6 rounded-xl border p-4 sm:p-6">
        <header className="space-y-2" data-tour="app-connections">
          <h2 className="text-xl font-medium">{t("title")}</h2>
          <p className="text-muted-foreground text-sm">{t("description")}</p>
        </header>
        {journey.catalog.data && !journey.catalog.data.configured && (
          <div role="status" className="bg-muted rounded-lg p-4 text-sm">
            <p className="font-medium">{t("unconfiguredTitle")}</p>
            <p className="text-muted-foreground mt-1">{t("unconfiguredDescription")}</p>
          </div>
        )}
        <ol
          className="text-muted-foreground flex flex-wrap gap-x-6 gap-y-2 text-sm"
          aria-label={t("progress")}
        >
          {([1, 2, 3] as const).map((step) => (
            <li
              key={step}
              aria-current={journey.step === step ? "step" : undefined}
              className={journey.step === step ? "text-foreground font-medium" : undefined}
            >
              {t(`steps.${step}`)}
            </li>
          ))}
        </ol>
        {journey.step === 1 && (
          <ConnectionGoals goal={journey.goal} onChange={journey.chooseGoal} />
        )}
        {journey.step === 2 && (
          <ConnectionCatalog
            apps={apps}
            connections={connections}
            goal={journey.goal}
            requestedToolkit={requestedToolkit}
            busy={journey.busy}
            search={journey.catalogSearch}
            onSearch={journey.setCatalogSearch}
            loading={journey.catalog.isLoading}
            loadingMore={journey.catalog.isFetchingNextPage}
            hasMore={journey.catalog.hasNextPage}
            catalogAvailable={journey.catalog.data?.catalog_available ?? false}
            error={journey.catalog.error ? getErrorMessage(journey.catalog.error, tErrors) : null}
            onLoadMore={() => void journey.catalog.fetchNextPage()}
            onRetry={() => void journey.catalog.refetch()}
            onConnect={(app) => {
              journey.setError(null);
              journey.setAuthorization({ app });
            }}
          />
        )}
        {journey.step === 3 && (
          <ConnectionFirstTask
            goal={journey.goal}
            connections={connections}
            scope={scope}
            onConnect={() => journey.setStep(2)}
          />
        )}
        {journey.complete.isPending && (
          <p role="status" className="text-muted-foreground text-sm">
            {t("verifying")}
          </p>
        )}
        {journey.message && (
          <p role="status" className="text-muted-foreground text-sm">
            {journey.message}
          </p>
        )}
        {journey.error && !journey.authorization && !journey.disconnecting && (
          <div role="alert" className="space-y-2">
            <p className="text-destructive text-sm">{journey.error}</p>
            {journey.callbackPending && (
              <Button
                variant="outline"
                disabled={journey.busy}
                onClick={() => void journey.verifyCallback()}
              >
                {t("retryVerification")}
              </Button>
            )}
          </div>
        )}
        <div className="text-muted-foreground flex items-start gap-2 text-xs">
          <ShieldCheck className="mt-0.5 size-4 shrink-0" aria-hidden />
          <p>{t("permissionHint")}</p>
        </div>
        <footer className="flex flex-wrap items-center justify-between gap-3 border-t pt-4">
          <div className="flex gap-2">
            {journey.step > 1 && (
              <Button
                variant="ghost"
                disabled={journey.busy}
                onClick={() => journey.setStep(journey.step === 3 ? 2 : 1)}
              >
                {t("back")}
              </Button>
            )}
            {journey.step < 3 && (
              <Button variant="ghost" disabled={journey.busy} onClick={() => journey.setStep(3)}>
                {t("skip")}
              </Button>
            )}
          </div>
          {journey.step < 3 && (
            <Button
              disabled={journey.busy}
              onClick={() => journey.setStep(journey.step === 1 ? 2 : 3)}
            >
              {t(journey.step === 1 ? "chooseApps" : "continue")}
              <ArrowRight aria-hidden />
            </Button>
          )}
        </footer>
      </section>
      <ConnectionAccounts
        connections={connections}
        busy={journey.busy}
        onEnable={(connection) =>
          void journey.perform(() => journey.enable.mutateAsync(connection.id), t("enabled"))
        }
        onReconnect={(connection) => {
          const app = connection.app;
          if (app) {
            journey.setError(null);
            journey.setAuthorization({ app, connection });
          }
        }}
        onRefresh={(connection) =>
          void journey.perform(
            () => journey.refreshConnection.mutateAsync(connection.id),
            t("connectionChecked"),
          )
        }
        onDisconnect={(connection) => {
          journey.setError(null);
          journey.setDisconnecting(connection);
        }}
        onDefault={(connection) =>
          void journey.perform(
            () => journey.setDefault.mutateAsync(connection.id),
            t("defaultChanged"),
          )
        }
      />
      {journey.authorization && (
        <ConnectionAuthorizationDialog
          key={journey.authorization.connection?.id ?? journey.authorization.app.key}
          target={journey.authorization}
          busy={journey.busy}
          error={journey.error}
          onClose={() => {
            journey.setAuthorization(null);
            journey.setError(null);
          }}
          onContinue={(label) => void journey.authorize(label)}
        />
      )}
      {journey.disconnecting && (
        <ConnectionDisconnectDialog
          connection={journey.disconnecting}
          busy={journey.busy}
          error={journey.error}
          onClose={() => {
            journey.setDisconnecting(null);
            journey.setError(null);
          }}
          onConfirm={() => {
            const connection = journey.disconnecting;
            if (connection)
              void journey.perform(
                () => journey.remove.mutateAsync(connection.id),
                t("disconnected"),
              );
          }}
        />
      )}
    </div>
  );
}
