"use client";

import { useEffect, useId, useRef, useState } from "react";
import { ListTodo, Maximize2, Minimize2, Search, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { Button } from "@/components/ui";
import { useConversationTasks, type ConversationTask } from "@/hooks/use-conversation-tasks";
import { BackgroundTaskList } from "./background-tasks";
import { BrowserPanelFrame } from "./browser-panel-frame";

const GROUPS = ["needsYou", "working", "waiting", "finished"] as const;
const TASK_GROUP: Record<ConversationTask["status"], (typeof GROUPS)[number]> = {
  awaiting_approval: "needsYou",
  awaiting_answer: "needsYou",
  running: "working",
  queued: "waiting",
  completed: "finished",
  failed: "finished",
  cancelled: "finished",
  interrupted: "finished",
};

/** The existing member-scoped task listing, opened without starting any work. */
export function WorkspaceTasksPanel({
  panelId,
  conversationId,
  readOnly,
  onClose,
}: {
  panelId: string;
  conversationId: string | null;
  readOnly: boolean;
  onClose: () => void;
}) {
  const t = useTranslations("chat.workspaceTasks");
  const common = useTranslations("common");
  const workspace = useTranslations("chat.workspace");
  const [all, setAll] = useState(conversationId === null);
  const [search, setSearch] = useState("");
  const state = useConversationTasks(all ? null : conversationId);
  const searchId = useId();
  const groupId = useId();
  const closeButton = useRef<HTMLButtonElement>(null);
  const opener = useRef<Element | null>(null);
  const dismiss = () => {
    onClose();
    if (opener.current instanceof HTMLElement && opener.current.isConnected) opener.current.focus();
  };
  useEffect(() => {
    opener.current = document.activeElement;
    closeButton.current?.focus();
  }, []);
  const tasks = state.data ?? [];
  const query = search.trim().toLowerCase();
  const matching = tasks.filter((task) => task.title.toLowerCase().includes(query));
  return (
    <BrowserPanelFrame
      id={panelId}
      label={t("title")}
      resizeLabel={workspace("resize")}
      initialWidth={35}
    >
      {({ fullscreen, toggleFullscreen }) => (
        <div
          className="flex min-h-0 flex-1 flex-col"
          onKeyDown={(event) => {
            if (event.key === "Escape" && !event.defaultPrevented) {
              event.preventDefault();
              event.stopPropagation();
              if (search) setSearch("");
              else dismiss();
            }
          }}
        >
          <header className="border-border flex shrink-0 items-center gap-2 border-b px-4 py-3">
            <ListTodo className="text-muted-foreground size-4" aria-hidden />
            <h2 className="min-w-0 flex-1 truncate text-sm font-semibold">{t("title")}</h2>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              onClick={toggleFullscreen}
              aria-label={t(fullscreen ? "restore" : "expand")}
            >
              {fullscreen ? (
                <Minimize2 className="size-4" aria-hidden />
              ) : (
                <Maximize2 className="size-4" aria-hidden />
              )}
            </Button>
            <Button
              ref={closeButton}
              type="button"
              variant="ghost"
              size="icon"
              onClick={dismiss}
              aria-label={t("close")}
            >
              <X className="size-4" aria-hidden />
            </Button>
          </header>
          <div className="space-y-3 border-b p-4">
            <p className="text-muted-foreground text-xs">{t("scopeHint")}</p>
            <div role="group" aria-label={t("scope")} className="flex flex-wrap gap-2">
              <Button
                type="button"
                size="sm"
                variant={all ? "outline" : "secondary"}
                aria-pressed={!all}
                disabled={conversationId === null}
                onClick={() => setAll(false)}
              >
                {t("thisChat")}
              </Button>
              <Button
                type="button"
                size="sm"
                variant={all ? "secondary" : "outline"}
                aria-pressed={all}
                onClick={() => setAll(true)}
              >
                {t("allMine")}
              </Button>
            </div>
            <label htmlFor={searchId} className="sr-only">
              {t("search")}
            </label>
            <div className="border-input flex items-center gap-2 rounded-lg border px-3">
              <Search className="text-muted-foreground size-4 shrink-0" aria-hidden />
              <input
                id={searchId}
                type="search"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
                placeholder={t("search")}
                className="h-10 min-w-0 flex-1 bg-transparent text-sm outline-none"
              />
            </div>
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain p-3">
            {state.isPending ? (
              <p role="status" className="text-muted-foreground p-3 text-sm">
                {common("loading")}
              </p>
            ) : state.error ? (
              <div role="alert" className="space-y-2 p-3 text-sm">
                <p>{t("loadFailed")}</p>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  onClick={() => void state.refetch()}
                >
                  {common("retry")}
                </Button>
              </div>
            ) : matching.length === 0 ? (
              <p role="status" className="text-muted-foreground p-3 text-sm">
                {t(tasks.length === 0 ? "empty" : "noMatches")}
              </p>
            ) : (
              GROUPS.map((group) => {
                const items = matching.filter((task) => TASK_GROUP[task.status] === group);
                if (items.length === 0) return null;
                return (
                  <section key={group} aria-labelledby={`${groupId}-${group}`} className="mb-4">
                    <h3
                      id={`${groupId}-${group}`}
                      className="text-muted-foreground px-2 text-xs font-medium"
                    >
                      {t(`groups.${group}`, { count: items.length })}
                    </h3>
                    <BackgroundTaskList
                      tasks={items}
                      stopping={state.stop.isPending}
                      onStop={readOnly ? undefined : state.stop.mutate}
                    />
                  </section>
                );
              })
            )}
          </div>
        </div>
      )}
    </BrowserPanelFrame>
  );
}
