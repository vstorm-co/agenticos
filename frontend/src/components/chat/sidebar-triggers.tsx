"use client";

import { useState } from "react";
import { CalendarClock, ChevronDown, ChevronRight, MoreHorizontal } from "lucide-react";
import { useTranslations } from "next-intl";

import { TriggerFormDialog } from "@/components/triggers/trigger-form-dialog";
import { TriggerRunsSheet } from "@/components/triggers/trigger-runs-view";
import { TriggerSummary } from "@/components/triggers/trigger-summary";
import {
  Button,
  ConfirmDialog,
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
  Skeleton,
} from "@/components/ui";
import { useOrgTriggers } from "@/hooks/use-org-triggers";
import { useTriggers } from "@/hooks/use-triggers";
import { cn } from "@/lib/utils";
import type { Trigger } from "@/types/triggers";

/**
 * The chat sidebar's schedules-and-triggers section, above the conversation list.
 *
 * Collapsed by default and fetched only when expanded, so the sidebar's first
 * paint costs no extra request. Clicking an item opens its run log in the same
 * read-only drawer every other trigger surface uses - not the chat screen, whose
 * composer this ownerless log would refuse every send from. A trigger that has
 * never fired opens it empty, which is what clicking it should show. The row
 * menu carries the rest: edit, pause or resume, run now, delete.
 *
 * Each row gates its own manage controls on the trigger's `can_manage`, resolved
 * per row by the server: a Viewer holding an explicit run grant on one agent gets
 * that agent's rows' menus and editor, and only informational rows for the rest.
 */
export function SidebarTriggers() {
  const t = useTranslations("triggers");
  const [expanded, setExpanded] = useState(false);
  const { triggers, isLoading, isError } = useOrgTriggers(expanded);
  const [editing, setEditing] = useState<Trigger | null>(null);
  const [viewing, setViewing] = useState<Trigger | null>(null);

  return (
    <div className="border-b px-3 pb-2">
      <button
        type="button"
        onClick={() => setExpanded((previous) => !previous)}
        aria-expanded={expanded}
        className="text-muted-foreground hover:text-foreground flex h-8 w-full items-center gap-2 rounded-lg px-3 text-xs font-medium transition-colors"
      >
        {expanded ? (
          <ChevronDown className="h-3 w-3 shrink-0" aria-hidden />
        ) : (
          <ChevronRight className="h-3 w-3 shrink-0" aria-hidden />
        )}
        <CalendarClock className="h-3.5 w-3.5 shrink-0" aria-hidden />
        {t("sectionTitle")}
      </button>

      {expanded && (
        <div className="mt-1 space-y-1">
          {isLoading ? (
            <div className="space-y-1">
              {[1, 2].map((row) => (
                <Skeleton key={row} className="h-9 w-full rounded-md" />
              ))}
            </div>
          ) : isError ? (
            <p className="text-destructive px-3 py-1 text-xs">{t("sectionError")}</p>
          ) : triggers.length === 0 ? (
            <p className="text-muted-foreground px-3 py-1 text-xs">{t("sectionEmpty")}</p>
          ) : (
            triggers.map((trigger) => (
              <SidebarTriggerItem
                key={trigger.id}
                trigger={trigger}
                onOpen={() => setViewing(trigger)}
                onEdit={() => setEditing(trigger)}
              />
            ))
          )}
        </div>
      )}

      {viewing && (
        <TriggerRunsSheet
          trigger={viewing}
          pendingSince={null}
          open
          onOpenChange={(next) => !next && setViewing(null)}
        />
      )}
      {editing && (
        <TriggerFormDialog
          agentId={editing.agent_id}
          open
          trigger={editing}
          onOpenChange={(next) => !next && setEditing(null)}
        />
      )}
    </div>
  );
}

function SidebarTriggerItem({
  trigger,
  onOpen,
  onEdit,
}: {
  trigger: Trigger;
  onOpen: () => void;
  onEdit: () => void;
}) {
  const t = useTranslations("triggers");
  const { setActive, runNow, remove } = useTriggers(trigger.agent_id);
  const [confirmingDelete, setConfirmingDelete] = useState(false);
  const title = trigger.name ?? trigger.agent_name ?? "";

  return (
    <div className="group hover:bg-secondary flex items-center rounded-md transition-colors">
      <button
        type="button"
        onClick={onOpen}
        className="min-w-0 flex-1 px-3 py-1.5 text-left"
        aria-label={t("openItem", { agent: title })}
      >
        <span
          className={cn(
            "block truncate text-xs font-medium",
            !trigger.is_active && "text-muted-foreground line-through",
          )}
        >
          {title}
        </span>
        <span className="text-muted-foreground block truncate text-[11px]">
          <TriggerSummary trigger={trigger} />
        </span>
      </button>
      {trigger.can_manage && (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              variant="ghost"
              size="sm"
              className="h-7 w-7 shrink-0 p-0 opacity-0 group-hover:opacity-100 focus-visible:opacity-100 data-[state=open]:opacity-100"
              aria-label={t("itemActions", { agent: title })}
            >
              <MoreHorizontal className="h-3.5 w-3.5" aria-hidden />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end">
            <DropdownMenuItem onSelect={onEdit}>{t("edit")}</DropdownMenuItem>
            <DropdownMenuItem
              disabled={!trigger.is_active || runNow.isPending}
              onSelect={() => runNow.mutate(trigger.id)}
            >
              {t("runNow")}
            </DropdownMenuItem>
            <DropdownMenuItem
              disabled={setActive.isPending}
              onSelect={() =>
                setActive.mutate({ triggerId: trigger.id, isActive: !trigger.is_active })
              }
            >
              {trigger.is_active ? t("pause") : t("resume")}
            </DropdownMenuItem>
            <DropdownMenuItem
              className="text-destructive focus:text-destructive"
              disabled={remove.isPending}
              onSelect={() => setConfirmingDelete(true)}
            >
              {t("delete")}
            </DropdownMenuItem>
          </DropdownMenuContent>
        </DropdownMenu>
      )}
      <ConfirmDialog
        open={confirmingDelete}
        onOpenChange={setConfirmingDelete}
        title={t("deleteTitle")}
        description={t("deleteConfirm")}
        confirmLabel={t("delete")}
        destructive
        onConfirm={() => remove.mutate(trigger.id)}
      />
    </div>
  );
}
