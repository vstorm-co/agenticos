"use client";

import { useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { Inbox, Pencil, Radar, Trash2 } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { toast } from "sonner";

import { Skeleton } from "@/components/ui/skeleton";
import { ErrorState } from "@/components/states";
import { Badge, Button, ListCard, ListCardEmpty, Switch } from "@/components/ui";
import { useMcpConnections, useOrganizations } from "@/hooks";
import { useWatches } from "@/hooks/use-watches";
import { getErrorMessage } from "@/lib/api-error";
import { ROUTES } from "@/lib/constants";
import { timeAgo } from "@/lib/utils";
import { cadenceLabel } from "@/lib/watch-cadence";
import type { Watch } from "@/lib/watches-api";
import { WatchAccount } from "./watch-account";
import { WatchDialog } from "./watch-dialog";

/** Where the findings of watches are listed, already narrowed to them. */
export const WATCH_FINDINGS = `${ROUTES.INBOX}?filter=watches`;

/** Whether the person may start a watch here: the organization allows it and they have an account. */
export function useCanWatch(): boolean {
  const { activeOrg } = useOrganizations();
  const { connections } = useMcpConnections();
  return activeOrg?.proactive_watches_enabled === true && connections.length > 0;
}

/**
 * What the person has the platform watch in their own connections (#2301), under
 * Routines beside what runs on a schedule: each watch with its account, how often
 * it looks and when it last did, how many of its findings wait in the inbox, why
 * one that is on is not being read, and the controls to change, pause or remove it.
 */
export function WatchesCard({ onNew }: { onNew: () => void }) {
  const t = useTranslations("watches");
  const tc = useTranslations("common");
  const ts = useTranslations("states");
  const tErrors = useTranslations("errors");
  const router = useRouter();
  const { activeOrg } = useOrganizations();
  const { connections } = useMcpConnections();
  const { watches, isLoading, error, refetch, update, remove } = useWatches();
  // A connection whose sign-in lapsed is still "on", and a look through it reads
  // nothing - so the row says so rather than looking as if it were working.
  const lapsed = new Set(connections.filter((each) => !each.authorized).map((each) => each.id));
  const [editing, setEditing] = useState<Watch | null>(null);

  const allowed = activeOrg?.proactive_watches_enabled === true;
  const act = async (work: () => Promise<unknown>, done: string) => {
    try {
      await work();
      toast.success(done);
    } catch (error) {
      toast.error(getErrorMessage(error, tErrors));
    }
  };

  return (
    <ListCard
      title={t("title")}
      counted={isLoading || error ? null : t("count", { count: watches.length })}
      contentClassName="p-0"
      headerTour="routines-watches"
      controls={
        watches.length > 0 && (
          <Button asChild variant="ghost" size="sm">
            <Link href={WATCH_FINDINGS}>
              <Inbox className="h-4 w-4" aria-hidden />
              {t("findings")}
            </Link>
          </Button>
        )
      }
    >
      {error ? (
        <ErrorState cta={{ label: tc("retry"), onClick: () => void refetch() }} />
      ) : isLoading ? (
        <ul className="divide-border divide-y" role="status" aria-label={ts("loading")}>
          {[0, 1].map((watch) => (
            <li
              key={watch}
              className="flex flex-wrap items-center gap-x-3 gap-y-2 px-4 py-3 sm:flex-nowrap sm:px-5"
              aria-hidden
            >
              <div className="min-w-0 flex-1 space-y-1">
                <Skeleton className="h-5 w-1/3" />
                <Skeleton className="h-4 w-2/3" />
              </div>
              <Skeleton className="h-8 w-24" />
            </li>
          ))}
        </ul>
      ) : watches.length > 0 ? (
        <ul className="divide-border divide-y">
          {watches.map((watch) => (
            <WatchRow
              key={watch.id}
              watch={watch}
              lapsed={lapsed.has(watch.connection_id)}
              onEdit={() => setEditing(watch)}
              onToggle={(on) =>
                act(
                  () => update({ id: watch.id, changes: { is_active: on } }),
                  on ? t("resumed") : t("paused"),
                )
              }
              onRemove={() => act(() => remove(watch.id), t("removed"))}
            />
          ))}
        </ul>
      ) : !allowed ? (
        <ListCardEmpty icon={Radar} title={t("offTitle")} description={t("orgOff")} />
      ) : connections.length === 0 ? (
        <ListCardEmpty
          icon={Radar}
          title={t("noConnectionsTitle")}
          description={t("noConnections")}
          cta={{ label: t("connect"), onClick: () => router.push(ROUTES.MCP_SERVERS) }}
        />
      ) : (
        <ListCardEmpty
          icon={Radar}
          title={t("emptyTitle")}
          description={t("emptyDescription")}
          cta={{ label: t("add"), onClick: onNew }}
        />
      )}
      {editing && (
        <WatchDialog open onOpenChange={(open) => !open && setEditing(null)} watch={editing} />
      )}
    </ListCard>
  );
}

function WatchRow({
  watch,
  lapsed,
  onEdit,
  onToggle,
  onRemove,
}: {
  watch: Watch;
  lapsed: boolean;
  onEdit: () => void;
  onToggle: (on: boolean) => void;
  onRemove: () => void;
}) {
  const t = useTranslations("watches");
  const tCadence = useTranslations("watches.cadence");
  const tTime = useTranslations("time");
  const locale = useLocale();
  const cadence = cadenceLabel(watch.interval_minutes, tCadence);
  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-2 px-4 py-3 sm:flex-nowrap sm:px-5">
      <div className="min-w-0 flex-1 space-y-1">
        <p className="truncate text-sm font-medium">{watch.title}</p>
        <div className="text-muted-foreground flex min-w-0 items-center gap-1.5 text-xs">
          <WatchAccount
            server={watch.server}
            connectionName={watch.connection_name}
            className="text-foreground/80 shrink-0"
          />
          <span aria-hidden>·</span>
          <span className="truncate">
            {watch.last_run_at
              ? t("rowLooked", { cadence, when: timeAgo(watch.last_run_at, tTime, locale) })
              : t("rowFirst", { cadence })}
          </span>
        </div>
      </div>
      {watch.waiting > 0 && (
        <Link
          href={WATCH_FINDINGS}
          className="bg-primary/10 text-primary hover:bg-primary/15 rounded-full px-2.5 py-0.5 text-xs font-medium"
        >
          {t("waiting", { count: watch.waiting })}
        </Link>
      )}
      {watch.urgent && <Badge variant="secondary">{t("urgentBadge")}</Badge>}
      {watch.is_active && watch.stopped && (
        <Badge variant="outline">{t(`stopped.${watch.stopped}`)}</Badge>
      )}
      {watch.is_active && !watch.stopped && lapsed && (
        <Badge variant="outline">{t("signInAgain")}</Badge>
      )}
      <div className="flex items-center gap-1">
        <Switch
          checked={watch.is_active}
          onCheckedChange={onToggle}
          aria-label={t("activeLabel", { title: watch.title })}
        />
        <Button
          variant="ghost"
          size="icon"
          onClick={onEdit}
          aria-label={t("editLabel", { title: watch.title })}
        >
          <Pencil className="h-4 w-4" />
        </Button>
        <Button
          variant="ghost"
          size="icon"
          onClick={onRemove}
          aria-label={t("removeLabel", { title: watch.title })}
        >
          <Trash2 className="h-4 w-4" />
        </Button>
      </div>
    </li>
  );
}
