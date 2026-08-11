"use client";

import { useState } from "react";
import { CalendarClock, ChevronDown, ChevronRight, MoreHorizontal } from "lucide-react";
import { useTranslations } from "next-intl";

import { TriggerFormDialog } from "@/components/triggers/trigger-form-dialog";
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
 * paint costs no extra request. Clicking an item opens its run-log conversation -
 * the one list every fire appends to, opened eagerly on create - so a trigger
 * that has never fired opens it empty rather than on a config form; that is what
 * a user expects clicking it. Only a trigger with no conversation at all (an
 * older row, or one whose log was deleted) falls back to the editor. The row menu
 * carries the rest: edit, pause or resume, run now, delete.
 */
export function SidebarTriggers({
  onOpenConversation,
  canManage,
}: {
  /** Opens a conversation in the chat - the sidebar's own selection handler. */
  onOpenConversation: (conversationId: string) => void;
  /** Whether the caller may manage triggers (`agents:run`). A viewer still sees
   *  the list but gets no row menu and no editor. */
  canManage: boolean;
}) {
  const t = useTranslations("triggers");
  const [expanded, setExpanded] = useState(false);
  const { triggers, isLoading, isError } = useOrgTriggers(expanded);
  const [editing, setEditing] = useState<Trigger | null>(null);

  function openItem(trigger: Trigger) {
    if (trigger.conversation_id !== null) {
      // Open its run-log conversation whether or not it has fired: a run-less
      // trigger opens it empty, which is what clicking the item should show.
      onOpenConversation(trigger.conversation_id);
    } else if (canManage) {
      // No conversation to show (an older trigger, or its log was deleted): fall
      // back to the editor, which a viewer may not use, so for them the item is
      // informational only.
      setEditing(trigger);
    }
  }

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
                canManage={canManage}
                onOpen={() => openItem(trigger)}
                onEdit={() => setEditing(trigger)}
              />
            ))
          )}
        </div>
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
  canManage,
  onOpen,
  onEdit,
}: {
  trigger: Trigger;
  canManage: boolean;
  onOpen: () => void;
  onEdit: () => void;
}) {
  const t = useTranslations("triggers");
  const { setActive, runNow, remove } = useTriggers(trigger.agent_id);
  const [confirmingDelete, setConfirmingDelete] = useState(false);

  return (
    <div className="group hover:bg-secondary flex items-center rounded-md transition-colors">
      <button
        type="button"
        onClick={onOpen}
        className="min-w-0 flex-1 px-3 py-1.5 text-left"
        aria-label={t("openItem", { agent: trigger.agent_name ?? "" })}
      >
        <span
          className={cn(
            "block truncate text-xs font-medium",
            !trigger.is_active && "text-muted-foreground line-through",
          )}
        >
          {trigger.agent_name}
        </span>
        <span className="text-muted-foreground block truncate text-[11px]">
          <TriggerSummary trigger={trigger} />
        </span>
      </button>
      {canManage && (
        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              variant="ghost"
              size="sm"
              className="h-7 w-7 shrink-0 p-0 opacity-0 group-hover:opacity-100 focus-visible:opacity-100 data-[state=open]:opacity-100"
              aria-label={t("itemActions", { agent: trigger.agent_name ?? "" })}
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
