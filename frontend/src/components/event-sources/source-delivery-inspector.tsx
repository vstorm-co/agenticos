"use client";

import { ArrowDownToLine, ArrowLeft, ArrowUpFromLine, RefreshCw } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";
import { CopyButton } from "@/components/chat/copy-button";
import { ErrorState, LoadingState } from "@/components/states";
import { Badge, Button, DialogFooter } from "@/components/ui";
import { useEventSourceDelivery } from "@/hooks/use-event-sources";
import { DIALOG_BODY } from "@/lib/dialog-sizes";
import type { EventSourceDeliveryDetail } from "@/lib/event-sources-api";

export function SourceDeliveryInspector({
  sourceId,
  deliveryId,
  onBack,
}: {
  sourceId: string;
  deliveryId: string;
  onBack: () => void;
}) {
  const t = useTranslations("eventSources.deliveries.inspector");
  const labels = useTranslations("eventSources.deliveries");
  const eventSources = useTranslations("eventSources");
  const detail = useEventSourceDelivery(sourceId, deliveryId);

  return (
    <>
      <div className={DIALOG_BODY}>
        {detail.error ? (
          <ErrorState description={t("loadError")} />
        ) : detail.data ? (
          <DeliveryExchange delivery={detail.data} />
        ) : (
          <LoadingState variant="pending" />
        )}
      </div>
      <DialogFooter>
        <Button type="button" variant="ghost" className="mr-auto" onClick={onBack}>
          <ArrowLeft className="rtl:rotate-180" aria-hidden />
          {t("back")}
        </Button>
        <Button
          type="button"
          variant="outline"
          loading={detail.isFetching}
          onClick={() => void detail.refetch()}
        >
          <RefreshCw aria-hidden />
          {detail.error ? eventSources("retry") : labels("refresh")}
        </Button>
      </DialogFooter>
    </>
  );
}

function DeliveryExchange({ delivery }: { delivery: EventSourceDeliveryDetail }) {
  const t = useTranslations("eventSources.deliveries.inspector");
  const format = useFormatter();
  const body = delivery.request.body;
  const formattedBody = body === null ? null : JSON.stringify(body, null, 2);

  return (
    <div className="space-y-4">
      <dl className="bg-muted/50 flex flex-wrap gap-x-6 gap-y-2 rounded-lg px-3 py-2 text-xs">
        <div className="min-w-0">
          <dt className="text-muted-foreground">{t("receiptId")}</dt>
          <dd className="font-mono break-all" dir="ltr">
            {delivery.id}
          </dd>
        </div>
        <div>
          <dt className="text-muted-foreground">{t("receivedAt")}</dt>
          <dd>
            <time dateTime={delivery.received_at}>
              {format.dateTime(new Date(delivery.received_at), {
                dateStyle: "medium",
                timeStyle: "medium",
              })}
            </time>
          </dd>
        </div>
        {delivery.external_id !== null && (
          <div className="min-w-0">
            <dt className="text-muted-foreground">{t("senderId")}</dt>
            <dd className="font-mono break-all" dir="ltr">
              {delivery.external_id}
            </dd>
          </div>
        )}
      </dl>

      <div className="grid items-start gap-3 sm:grid-cols-2">
        <section className="border-border min-w-0 space-y-3 rounded-xl border p-3">
          <h3 className="flex flex-wrap items-center gap-2 text-sm font-semibold">
            <ArrowDownToLine className="text-muted-foreground size-4" aria-hidden />
            {t("request")}
            <Badge variant="outline">{delivery.request.method}</Badge>
          </h3>
          <DeliveryHeaders title={t("retainedHeaders")} headers={delivery.request.headers} />
          <div>
            <div className="mb-1 flex items-center justify-between gap-2">
              <h4 className="text-muted-foreground text-xs font-medium">{t("body")}</h4>
              {formattedBody !== null && (
                <CopyButton text={formattedBody} label={t("copyBody")} className="opacity-100" />
              )}
            </div>
            {formattedBody === null ? (
              <p className="text-muted-foreground text-xs">{t("bodyUnavailable")}</p>
            ) : (
              <pre className="bg-muted max-h-64 overflow-auto rounded-md p-2 text-xs" dir="ltr">
                {formattedBody}
              </pre>
            )}
          </div>
        </section>
        <section className="border-border min-w-0 space-y-3 rounded-xl border p-3">
          <h3 className="flex flex-wrap items-center gap-2 text-sm font-semibold">
            <ArrowUpFromLine className="text-muted-foreground size-4" aria-hidden />
            {t("response")}
            <Badge variant="success">
              {t("statusCode", { status: delivery.response.status_code })}
            </Badge>
          </h3>
          <DeliveryHeaders title={t("headers")} headers={delivery.response.headers} />
          <div className="space-y-1">
            <h4 className="text-muted-foreground text-xs font-medium">{t("body")}</h4>
            <p className="text-muted-foreground text-xs">{t("emptyResponse")}</p>
          </div>
        </section>
      </div>
      <DeliveryDispatches dispatches={delivery.dispatches} />
    </div>
  );
}

function DeliveryHeaders({ title, headers }: { title: string; headers: Record<string, string> }) {
  const t = useTranslations("eventSources.deliveries.inspector");
  const entries = Object.entries(headers);
  return (
    <div className="space-y-1">
      <h4 className="text-muted-foreground text-xs font-medium">{title}</h4>
      {entries.length ? (
        <dl className="bg-muted divide-border divide-y rounded-md px-2 font-mono text-xs" dir="ltr">
          {entries.map(([name, value]) => (
            <div key={name} className="grid gap-x-3 gap-y-0.5 py-1.5 break-all sm:grid-cols-2">
              <dt className="text-muted-foreground">{name}</dt>
              <dd>{value}</dd>
            </div>
          ))}
        </dl>
      ) : (
        <p className="text-muted-foreground text-xs">{t("noHeaders")}</p>
      )}
    </div>
  );
}

const statusVariants = {
  pending: "warning",
  admitted: "secondary",
  skipped: "outline",
  failed: "destructive",
} as const;

function DeliveryDispatches({
  dispatches,
}: {
  dispatches: EventSourceDeliveryDetail["dispatches"];
}) {
  const t = useTranslations("eventSources.deliveries");
  const format = useFormatter();

  return (
    <section className="border-border space-y-2 rounded-xl border p-3">
      <h3 className="text-sm font-semibold">{t("dispatch")}</h3>
      {dispatches.length === 0 ? (
        <p className="text-muted-foreground text-xs">{t("noDispatches")}</p>
      ) : (
        <ul className="divide-border divide-y">
          {dispatches.map((dispatch) => (
            <li key={dispatch.id} className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2">
              <Badge variant={statusVariants[dispatch.status]}>
                {t(`inspector.states.${dispatch.status}`)}
              </Badge>
              <code className="text-muted-foreground text-xs break-all" dir="ltr">
                {dispatch.id}
              </code>
              {dispatch.error_code !== null && (
                <code className="text-destructive-ink text-xs break-all" dir="ltr">
                  {dispatch.error_code}
                </code>
              )}
              {dispatch.completed_at !== null && (
                <time className="text-muted-foreground text-xs" dateTime={dispatch.completed_at}>
                  {format.dateTime(new Date(dispatch.completed_at), {
                    dateStyle: "medium",
                    timeStyle: "medium",
                  })}
                </time>
              )}
            </li>
          ))}
        </ul>
      )}
    </section>
  );
}
