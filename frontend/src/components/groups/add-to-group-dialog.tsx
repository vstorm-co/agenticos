"use client";

import { useState } from "react";
import { AppWindow, BookOpen, Bot, Check, Database, FileText, Plug, Search } from "lucide-react";
import { useTranslations } from "next-intl";

import { AgentFace } from "@/components/dashboard/agent-face";
import { ErrorState, LoadingState } from "@/components/states";
import {
  Button,
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
import { DIALOG_BODY, DIALOG_COLUMN, DIALOG_FORM } from "@/lib/dialog-sizes";
import { cn } from "@/lib/utils";
import type { Group, GroupResource } from "@/types/groups";
import type { GrantLevel } from "@/types/sharing";

/** Each kind's section: its mark and its heading, in the order a department is set up. */
const KINDS = [
  { kind: "agent", icon: Bot, heading: "resourceAgents" },
  { kind: "collection", icon: Database, heading: "resourceCollections" },
  { kind: "skill", icon: BookOpen, heading: "resourceSkills" },
  { kind: "context", icon: FileText, heading: "resourceContext" },
  { kind: "mcp_connection", icon: Plug, heading: "resourceMcpServers" },
  { kind: "artifact", icon: AppWindow, heading: "resourceApps" },
] as const satisfies readonly {
  kind: GroupResource["kind"];
  icon: typeof Bot;
  heading: string;
}[];

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

  const toggleAll = (items: GroupResource[], on: boolean) =>
    setPicked((current) => {
      const next = new Set(current);
      for (const item of items) {
        if (on) next.add(key(item));
        else next.delete(key(item));
      }
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
        <div className={cn(DIALOG_BODY, "space-y-5")}>
          {error ? (
            <ErrorState description={getErrorMessage(error, tErrors)} />
          ) : isLoading ? (
            <LoadingState variant="skeleton-panel" rows={3} />
          ) : shown.length === 0 ? (
            <p className="text-muted-foreground py-6 text-center text-sm">
              {needle ? t("addToGroupNoMatch") : t("addToGroupNothing")}
            </p>
          ) : (
            // By kind, in the order a department is set up, rather than one
            // list of mixed names with a grey glyph each - "agent-instructions"
            // and "Architect" are different things to give a team.
            KINDS.map(({ kind, icon: Icon, heading }) => {
              const items = shown.filter((item) => item.kind === kind);
              if (items.length === 0) return null;
              const allPicked = items.every((item) => picked.has(key(item)));
              return (
                <section key={kind} className="space-y-2">
                  <div className="flex items-center gap-2">
                    <Icon className="text-muted-foreground h-4 w-4" aria-hidden />
                    <h3 className="text-sm font-medium">{t(heading)}</h3>
                    <span className="text-muted-foreground text-xs">{items.length}</span>
                    <button
                      type="button"
                      onClick={() => toggleAll(items, !allPicked)}
                      className="text-muted-foreground hover:text-foreground ml-auto text-xs underline-offset-4 hover:underline"
                    >
                      {allPicked ? t("addToGroupNone") : t("addToGroupAll")}
                    </button>
                  </div>
                  <div className="grid gap-1.5 sm:grid-cols-2">
                    {items.map((item) => {
                      const on = picked.has(key(item));
                      return (
                        <button
                          key={key(item)}
                          type="button"
                          role="checkbox"
                          aria-checked={on}
                          onClick={() => toggle(item)}
                          className={cn(
                            "flex min-w-0 items-center gap-2.5 rounded-lg border px-3 py-2 text-left text-sm transition-colors",
                            on
                              ? "border-foreground/40 bg-accent"
                              : "border-border hover:bg-accent/50",
                          )}
                        >
                          {item.kind === "agent" ? (
                            <AgentFace agentId={item.id} className="size-6 shrink-0" />
                          ) : (
                            <span className="bg-muted grid size-6 shrink-0 place-items-center rounded-md">
                              <Icon className="text-muted-foreground h-3.5 w-3.5" aria-hidden />
                            </span>
                          )}
                          <span className="min-w-0 flex-1 truncate">{item.name}</span>
                          <span
                            aria-hidden
                            className={cn(
                              "grid size-4 shrink-0 place-items-center rounded-[4px] border",
                              on
                                ? "border-foreground bg-foreground text-background"
                                : "border-border",
                            )}
                          >
                            {on && <Check className="h-3 w-3" />}
                          </span>
                        </button>
                      );
                    })}
                  </div>
                </section>
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
