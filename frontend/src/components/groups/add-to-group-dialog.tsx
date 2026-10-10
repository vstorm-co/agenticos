"use client";

import { useState } from "react";
import { AppWindow, BookOpen, Bot, Database, FileText, Plug, Search } from "lucide-react";
import { useTranslations } from "next-intl";

import { ErrorState, LoadingState } from "@/components/states";
import {
  Button,
  Checkbox,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Input,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { useGroupSharing } from "@/hooks";
import { getErrorMessage } from "@/lib/api-error";
import { DIALOG_COLUMN, DIALOG_FORM } from "@/lib/dialog-sizes";
import { cn } from "@/lib/utils";
import type { Group, GroupResource } from "@/types/groups";
import type { GrantLevel } from "@/types/sharing";

const KIND_ICON = {
  agent: Bot,
  collection: Database,
  skill: BookOpen,
  context: FileText,
  artifact: AppWindow,
  mcp_connection: Plug,
} as const satisfies Record<GroupResource["kind"], typeof Bot>;

const key = (item: GroupResource) => `${item.kind}:${item.id}`;

/**
 * Share several things with a department from its own page (#2072).
 *
 * Everything the reader may edit and the group does not have yet, of every kind,
 * with a search and a tick each - the other direction from each resource's Share
 * panel, which is one resource and many groups.
 */
export function AddToGroupDialog({
  orgId,
  group,
  onClose,
}: {
  orgId: string;
  group: Group;
  onClose: () => void;
}) {
  const t = useTranslations("groups");
  const tErrors = useTranslations("errors");
  const { shareable, isLoading, error, share } = useGroupSharing(orgId, group.id);
  const [query, setQuery] = useState("");
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [level, setLevel] = useState<GrantLevel>("use");

  const needle = query.trim().toLowerCase();
  const shown = shareable.filter((item) => item.name.toLowerCase().includes(needle));

  const toggle = (item: GroupResource) =>
    setPicked((current) => {
      const next = new Set(current);
      if (next.has(key(item))) next.delete(key(item));
      else next.add(key(item));
      return next;
    });

  const submit = () =>
    share.mutate(
      {
        items: shareable
          .filter((item) => picked.has(key(item)))
          .map((item) => ({ kind: item.kind, id: item.id })),
        level,
      },
      { onSuccess: onClose },
    );

  return (
    <Dialog open onOpenChange={onClose}>
      <DialogContent className={cn(DIALOG_FORM, DIALOG_COLUMN)}>
        <DialogHeader>
          <DialogTitle>{t("addToGroupTitle", { name: group.name })}</DialogTitle>
          <DialogDescription>{t("addToGroupWhy")}</DialogDescription>
        </DialogHeader>
        <div className="relative">
          <Search
            className="text-muted-foreground pointer-events-none absolute top-1/2 left-2.5 h-4 w-4 -translate-y-1/2"
            aria-hidden
          />
          <Input
            value={query}
            onChange={(event) => setQuery(event.target.value)}
            placeholder={t("addToGroupSearch")}
            aria-label={t("addToGroupSearch")}
            className="pl-8"
          />
        </div>
        <div className="min-h-0 flex-1 space-y-1 overflow-y-auto">
          {error ? (
            <ErrorState description={getErrorMessage(error, tErrors)} />
          ) : isLoading ? (
            <LoadingState variant="skeleton-panel" rows={3} />
          ) : shown.length === 0 ? (
            <p className="text-muted-foreground py-6 text-center text-sm">
              {needle ? t("addToGroupNoMatch") : t("addToGroupNothing")}
            </p>
          ) : (
            shown.map((item) => {
              const Icon = KIND_ICON[item.kind];
              const id = `share-${key(item)}`;
              return (
                <div
                  key={key(item)}
                  className="hover:bg-accent/50 flex items-center gap-3 rounded-md px-2 py-1.5"
                >
                  <Checkbox
                    id={id}
                    checked={picked.has(key(item))}
                    onCheckedChange={() => toggle(item)}
                  />
                  <Icon className="text-muted-foreground h-4 w-4 shrink-0" aria-hidden />
                  <Label htmlFor={id} className="flex-1 truncate font-normal">
                    {item.name}
                  </Label>
                </div>
              );
            })
          )}
        </div>
        <DialogFooter className="items-center gap-2 sm:justify-between">
          <div className="flex items-center gap-2">
            <Label htmlFor="add-to-group-level" className="text-muted-foreground text-xs">
              {t("addToGroupLevel")}
            </Label>
            <Select value={level} onValueChange={(next) => setLevel(next as GrantLevel)}>
              <SelectTrigger id="add-to-group-level" className="h-8 w-36">
                <SelectValue />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="read">{t("level.read")}</SelectItem>
                <SelectItem value="use">{t("level.use")}</SelectItem>
                <SelectItem value="edit">{t("level.edit")}</SelectItem>
              </SelectContent>
            </Select>
          </div>
          <Button onClick={submit} disabled={picked.size === 0 || share.isPending}>
            {t("addToGroupShare", { count: picked.size })}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
