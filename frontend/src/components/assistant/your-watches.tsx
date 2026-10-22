"use client";

import { useState } from "react";
import { Pencil, Plus, Trash2 } from "lucide-react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { McpServerIcon } from "@/components/mcp/mcp-server-icon";
import { SectionCard } from "@/components/settings/settings-section";
import { Badge, Button, Switch } from "@/components/ui";
import { useMcpCatalog, useMcpConnections, useOrganizations } from "@/hooks";
import { useWatches } from "@/hooks/use-watches";
import { getErrorMessage } from "@/lib/api-error";
import { cadenceLabel } from "@/lib/watch-cadence";
import type { Watch } from "@/lib/watches-api";
import { WatchDialog } from "./watch-dialog";

/**
 * What the person has the platform watch in their own connections (#2301): each
 * watch with how often it looks, whether it says urgent things at once, why one
 * that is on is not being read, and the controls to change, pause or remove it.
 */
export function YourWatches() {
  const t = useTranslations("watches");
  const tErrors = useTranslations("errors");
  const { activeOrg } = useOrganizations();
  const { connections } = useMcpConnections();
  const { watches, update, remove } = useWatches();
  const [editing, setEditing] = useState<Watch | "new" | null>(null);

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
    <SectionCard title={t("title")} description={t("description")}>
      <div className="space-y-4">
        {!allowed && <p className="text-muted-foreground text-sm">{t("orgOff")}</p>}
        {allowed && connections.length === 0 && (
          <p className="text-muted-foreground text-sm">{t("noConnections")}</p>
        )}
        {watches.length > 0 && (
          <ul className="divide-foreground/10 divide-y">
            {watches.map((watch) => (
              <WatchRow
                key={watch.id}
                watch={watch}
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
        )}
        {allowed && connections.length > 0 && (
          <Button variant="outline" size="sm" onClick={() => setEditing("new")}>
            <Plus className="h-4 w-4" />
            {t("add")}
          </Button>
        )}
      </div>
      {editing !== null && (
        <WatchDialog
          open
          onOpenChange={(open) => !open && setEditing(null)}
          watch={editing === "new" ? undefined : editing}
        />
      )}
    </SectionCard>
  );
}

function WatchRow({
  watch,
  onEdit,
  onToggle,
  onRemove,
}: {
  watch: Watch;
  onEdit: () => void;
  onToggle: (on: boolean) => void;
  onRemove: () => void;
}) {
  const t = useTranslations("watches");
  const tCadence = useTranslations("watches.cadence");
  const { servers } = useMcpCatalog();
  const entry = servers.find((server) => server.key === watch.server);
  return (
    <li className="flex items-center gap-3 py-2.5">
      <McpServerIcon icon={entry?.icon} name={watch.connection_name} url={entry?.url} />
      <div className="min-w-0 flex-1">
        <p className="truncate text-sm font-medium">{watch.title}</p>
        <p className="text-muted-foreground truncate text-xs">
          {t("rowDetail", {
            connection: watch.connection_name,
            cadence: cadenceLabel(watch.interval_minutes, tCadence),
          })}
        </p>
      </div>
      {watch.urgent && <Badge variant="secondary">{t("urgentBadge")}</Badge>}
      {watch.is_active && watch.stopped && (
        <Badge variant="outline">{t(`stopped.${watch.stopped}`)}</Badge>
      )}
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
    </li>
  );
}
