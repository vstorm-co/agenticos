"use client";
import { ArrowLeft, FolderTree, Layers, Network, RefreshCw, Search } from "lucide-react";
import { useTranslations } from "next-intl";
import { Button, Input } from "@/components/ui";
import { WorkspaceFullscreenButton } from "@/components/ui/workspace-fullscreen-button";

export function WikiToolbar({
  search,
  onSearch,
  count,
  links,
  busy,
  notesOpen,
  onNotes,
  groupsOpen,
  onGroups,
  onRefresh,
  expanded,
  onExpand,
  onClose,
}: {
  search: string;
  onSearch: (value: string) => void;
  count: number;
  links: number;
  busy: boolean;
  notesOpen: boolean;
  onNotes: () => void;
  groupsOpen: boolean;
  onGroups: () => void;
  onRefresh: () => void;
  expanded: boolean;
  onExpand: () => void;
  onClose: () => void;
}) {
  const t = useTranslations("wikiGraph");
  return (
    <div className="bg-card/95 flex w-full flex-wrap items-center gap-1 rounded-2xl border p-2 shadow-lg backdrop-blur-xl sm:w-auto sm:gap-2">
      <Button
        size="icon"
        variant="ghost"
        className="rounded-xl"
        aria-label={t("files")}
        onClick={onClose}
      >
        <ArrowLeft className="size-4" />
      </Button>
      <div className="flex items-center gap-2 sm:mr-2">
        <Network className="hidden size-4 text-violet-500 sm:block" aria-hidden />
        <div>
          <h2 className="text-xs font-semibold">{t("title")}</h2>
          <p className="text-muted-foreground text-[10px]">
            {t("counts", { pages: count, links })}
          </p>
        </div>
      </div>
      <div className="relative order-last w-full sm:order-none sm:w-60">
        <Search className="text-muted-foreground absolute top-2.5 left-2.5 size-3.5" aria-hidden />
        <Input
          aria-label={t("search")}
          placeholder={t("search")}
          value={search}
          onChange={(event) => onSearch(event.target.value)}
          className="bg-background/60 h-9 rounded-xl pl-8 text-xs"
        />
      </div>
      <Button
        size="icon"
        variant={notesOpen ? "secondary" : "ghost"}
        className="rounded-xl"
        aria-label={t("notes")}
        aria-pressed={notesOpen}
        onClick={onNotes}
      >
        <FolderTree className="size-4" />
      </Button>
      <Button
        size="icon"
        variant="ghost"
        className="rounded-xl"
        disabled={busy}
        aria-label={t("refresh")}
        title={t("automatic")}
        onClick={onRefresh}
      >
        <RefreshCw className={busy ? "size-4 animate-spin motion-reduce:animate-none" : "size-4"} />
      </Button>
      <Button
        size="icon"
        variant={groupsOpen ? "secondary" : "ghost"}
        className="rounded-xl"
        aria-label={t("groups")}
        aria-pressed={groupsOpen}
        onClick={onGroups}
      >
        <Layers className="size-4" />
      </Button>
      <WorkspaceFullscreenButton expanded={expanded} onToggle={onExpand} />
    </div>
  );
}
