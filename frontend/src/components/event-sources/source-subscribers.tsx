"use client";

import { ChevronRight } from "lucide-react";
import Link from "next/link";
import { useLocale, useTranslations } from "next-intl";
import {
  Button,
  Dialog,
  DialogClose,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
  Skeleton,
} from "@/components/ui";
import { useEventSourceUsage } from "@/hooks/use-event-sources";
import { ROUTES } from "@/lib/constants";
import { DIALOG_BODY, DIALOG_COLUMN, DIALOG_FORM } from "@/lib/dialog-sizes";
import type { EventSource } from "@/lib/event-sources-api";
import { getPathname } from "@/lib/locale-navigation";
import { cn } from "@/lib/utils";

export function SourceSubscribers({ source }: { source: EventSource }) {
  const t = useTranslations("eventSources");
  return (
    <Dialog>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm">
          {t("subscribers")}
        </Button>
      </DialogTrigger>
      <DialogContent className={cn(DIALOG_FORM, DIALOG_COLUMN)}>
        <DialogHeader>
          <DialogTitle>{t("subscribers")}</DialogTitle>
          <DialogDescription className="wrap-break-word">{source.name}</DialogDescription>
        </DialogHeader>
        <div className={DIALOG_BODY}>
          <SubscriberList sourceId={source.id} />
        </div>
      </DialogContent>
    </Dialog>
  );
}

function SubscriberList({ sourceId }: { sourceId: string }) {
  const t = useTranslations("eventSources");
  const locale = useLocale();
  const usage = useEventSourceUsage(sourceId);
  if (usage.error)
    return (
      <p role="alert" className="text-destructive-ink">
        {t("usageError")}
      </p>
    );
  if (!usage.data) return <Skeleton className="h-4 w-20" />;

  return (
    <div className="space-y-2 text-sm">
      <p className="text-muted-foreground">{t("usage", { count: usage.data.total })}</p>
      {usage.data.items.length > 0 && (
        <ul className="divide-border divide-y">
          {usage.data.items.map((item) => {
            if (item.target_id === null) {
              return (
                <li key={item.id} className="text-muted-foreground px-2 py-3">
                  {t(item.kind === "routine" ? "privateRoutine" : "privateWorkflow")}
                </li>
              );
            }
            const href =
              item.kind === "routine"
                ? { pathname: ROUTES.ROUTINES, query: { routine: item.target_id } }
                : `${ROUTES.WORKFLOWS}/${encodeURIComponent(item.target_id)}`;
            return (
              <li key={item.id}>
                <DialogClose asChild>
                  <Link
                    href={getPathname({ href, locale })}
                    className="hover:bg-muted focus-visible:ring-ring flex items-center justify-between gap-2 rounded-md px-2 py-3 focus-visible:ring-2"
                  >
                    <span className="min-w-0 wrap-break-word">
                      {item.name !== null && <>{item.name} · </>}
                      {t(item.kind)}
                      {item.is_active !== null && <> · {t(item.is_active ? "active" : "paused")}</>}
                    </span>
                    <ChevronRight
                      className="text-muted-foreground size-4 shrink-0 rtl:rotate-180"
                      aria-hidden
                    />
                  </Link>
                </DialogClose>
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
