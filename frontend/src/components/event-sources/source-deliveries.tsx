"use client";

import { History, RefreshCw } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";
import {
  Badge,
  Button,
  DataTable,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
  ListCardEmpty,
  type Column,
} from "@/components/ui";
import { useEventSourceDeliveries } from "@/hooks/use-event-sources";
import { DIALOG_BODY, DIALOG_COLUMN, DIALOG_WIDE } from "@/lib/dialog-sizes";
import type { EventSource, EventSourceDelivery } from "@/lib/event-sources-api";
import { cn } from "@/lib/utils";

const dispatches = [
  { status: "pending", variant: "warning" },
  { status: "admitted", variant: "secondary" },
  { status: "skipped", variant: "outline" },
  { status: "failed", variant: "destructive" },
] as const;

export function SourceDeliveries({ source }: { source: EventSource }) {
  const t = useTranslations("eventSources.deliveries");
  const title = t("forSource", { name: source.name });
  return (
    <Dialog>
      <DialogTrigger asChild>
        <Button
          variant="outline"
          size="sm"
          aria-label={title}
          className="h-auto min-h-8 max-w-full wrap-anywhere whitespace-normal"
          data-tour="event-sources-deliveries"
        >
          {t("title")}
        </Button>
      </DialogTrigger>
      <DialogContent className={cn(DIALOG_WIDE, DIALOG_COLUMN)}>
        <DialogHeader>
          <DialogTitle className="wrap-break-word">{title}</DialogTitle>
          <DialogDescription>{t("description")}</DialogDescription>
        </DialogHeader>
        <DeliveryHistory sourceId={source.id} />
      </DialogContent>
    </Dialog>
  );
}

function DeliveryHistory({ sourceId }: { sourceId: string }) {
  const t = useTranslations("eventSources.deliveries");
  const eventSources = useTranslations("eventSources");
  const format = useFormatter();
  const history = useEventSourceDeliveries(sourceId);
  const columns: Column<EventSourceDelivery>[] = [
    {
      key: "receipt",
      header: t("receipt"),
      className: "@md/table:w-1/2 @max-md/table:w-full",
      cell: ({ id, received_at }) => (
        <div className="space-y-1">
          <time dateTime={received_at}>
            {format.dateTime(new Date(received_at), { dateStyle: "medium", timeStyle: "medium" })}
          </time>
          <code className="text-muted-foreground block text-xs break-all" dir="ltr">
            {id}
          </code>
        </div>
      ),
    },
    {
      key: "dispatch",
      header: t("dispatch"),
      className: "@max-md/table:w-full",
      cell: (delivery) => {
        const outcomes = dispatches.filter(({ status }) => delivery[status] > 0);
        return outcomes.length ? (
          <div className="flex flex-wrap gap-1">
            {outcomes.map(({ status, variant }) => (
              <Badge key={status} variant={variant}>
                {t(status, { count: delivery[status] })}
              </Badge>
            ))}
          </div>
        ) : (
          <span className="text-muted-foreground">{t("noDispatches")}</span>
        );
      },
    },
  ];
  return (
    <>
      <div className={DIALOG_BODY}>
        <DataTable
          columns={columns}
          rows={history.error ? undefined : history.data?.items}
          loading={history.isLoading}
          getRowKey={(delivery) => delivery.id}
          empty={<ListCardEmpty icon={History} title={t("empty")} />}
          error={history.error ? t("loadError") : null}
          className="@md/table:[&_table]:table-fixed"
          skeletonRows={4}
          stackOnNarrow
        />
      </div>
      <DialogFooter>
        <Button
          type="button"
          variant="outline"
          loading={history.isFetching}
          onClick={() => void history.refetch()}
        >
          <RefreshCw className="size-4" aria-hidden />
          {history.error ? eventSources("retry") : t("refresh")}
        </Button>
      </DialogFooter>
    </>
  );
}
