"use client";
import { useCallback, useState } from "react";
import { useTranslations } from "next-intl";
import { History, Plus, X, PanelsTopLeft, Loader2, MessageSquare } from "lucide-react";
import { toast } from "sonner";
import { QuickAsk, type QuickAskTabState } from "./quick-ask";
import { RestoreQuickAsk, useQuickAskHistory } from "./quick-ask-history";
import { ChatScope } from "@/stores/chat-scope";
import { useAgentSelectionStore, useAuthStore } from "@/stores";
import { useTenantId } from "@/hooks/use-organizations";
import {
  Popover,
  PopoverTrigger,
  PopoverContent,
  SearchInput,
  useDebounced,
} from "@/components/ui";
import { newQuickAskWindow } from "@/lib/desktop/commands";
import { reportShellFailure } from "@/lib/desktop/shell";
import type { Conversation } from "@/types";

interface Tab extends QuickAskTabState {
  key: string;
  initialId: string | null;
}
const LIMIT = 8;
export function QuickAskWorkspace() {
  const user = useAuthStore((s) => s.user?.id);
  const tenant = useTenantId();
  return user ? <Workspace key={`${user}:${tenant}`} /> : <QuickAsk />;
}
function Workspace() {
  const t = useTranslations("desktop.quickAsk");
  const defaultAgent = useAgentSelectionStore((s) => s.selectedAgentId);
  const makeTab = (conversation?: Conversation): Tab => ({
    key: crypto.randomUUID(),
    initialId: conversation?.id ?? null,
    conversationId: conversation?.id ?? null,
    title: conversation?.title || t("newConversation"),
    processing: false,
    agentId: conversation?.agents?.[0]?.id ?? defaultAgent,
  });
  const [tabs, setTabs] = useState<Tab[]>(() => [makeTab()]);
  const [active, setActive] = useState(tabs[0]!.key);
  const [historyOpen, setHistoryOpen] = useState(false);
  const [search, setSearch] = useState("");
  const history = useQuickAskHistory(useDebounced(search, 250), historyOpen);
  const update = useCallback((key: string, state: QuickAskTabState) => {
    setTabs((tabs) =>
      tabs.map((tab) =>
        tab.key === key
          ? { ...tab, ...state, title: tab.initialId ? tab.title : state.title }
          : tab,
      ),
    );
  }, []);
  const open = (conversation?: Conversation) => {
    const found = conversation && tabs.find((tab) => tab.conversationId === conversation.id);
    if (found) setActive(found.key);
    else if (tabs.length < LIMIT) {
      const tab = makeTab(conversation);
      setTabs((tabs) => [...tabs, tab]);
      setActive(tab.key);
    } else {
      toast.error(t("tabLimit"));
      return;
    }
    setHistoryOpen(false);
  };
  const close = (key: string) => {
    const remaining = tabs.filter((tab) => tab.key !== key);
    if (!remaining.length) {
      const tab = makeTab();
      setTabs([tab]);
      setActive(tab.key);
    } else {
      setTabs(remaining);
      if (active === key)
        setActive(remaining[Math.max(0, tabs.findIndex((tab) => tab.key === key) - 1)]!.key);
    }
  };
  const toolbar = (
    <div className="border-border flex shrink-0 items-center gap-1 border-t px-2 py-1.5">
      <div
        role="tablist"
        aria-label={t("tabs")}
        className="flex min-w-0 flex-1 scrollbar-thin gap-1 overflow-x-auto"
      >
        {tabs.map((tab) => (
          <div
            key={tab.key}
            data-active={active === tab.key}
            className="group/tab bg-foreground/4 hover:bg-foreground/8 data-[active=true]:bg-foreground/10 flex shrink-0 items-center rounded-lg transition-colors motion-reduce:transition-none"
          >
            <button
              type="button"
              role="tab"
              id={`tab-${tab.key}`}
              aria-controls={`panel-${tab.key}`}
              aria-selected={active === tab.key}
              tabIndex={active === tab.key ? 0 : -1}
              onClick={() => setActive(tab.key)}
              onKeyDown={(event) => {
                const index = tabs.findIndex((item) => item.key === tab.key);
                const next =
                  event.key === "ArrowRight"
                    ? (index + 1) % tabs.length
                    : event.key === "ArrowLeft"
                      ? (index + tabs.length - 1) % tabs.length
                      : event.key === "Home"
                        ? 0
                        : event.key === "End"
                          ? tabs.length - 1
                          : null;
                if (next !== null) {
                  event.preventDefault();
                  setActive(tabs[next]!.key);
                  document.getElementById(`tab-${tabs[next]!.key}`)?.focus();
                }
              }}
              className="focus-visible:outline-ring flex max-w-40 items-center gap-1.5 rounded-lg px-2 py-1.5 text-xs aria-selected:font-medium"
            >
              {tab.processing ? (
                <Loader2 className="size-3 shrink-0 animate-spin" aria-hidden />
              ) : (
                <MessageSquare className="size-3 shrink-0" aria-hidden />
              )}
              <span className="truncate">{tab.title}</span>
            </button>
            <button
              type="button"
              onClick={() => close(tab.key)}
              aria-label={t("closeTab", { title: tab.title })}
              title={t("closeTab", { title: tab.title })}
              className="text-muted-foreground hover:text-foreground hover:bg-foreground/10 focus-visible:outline-ring mr-1 rounded-md p-1 opacity-0 transition-opacity duration-150 group-hover/tab:opacity-100 group-has-[:focus-visible]/tab:opacity-100 motion-reduce:transition-none [@media(hover:none)]:opacity-100"
            >
              <X className="size-3" aria-hidden />
            </button>
          </div>
        ))}
      </div>
      <button
        onClick={() => open()}
        disabled={tabs.length >= LIMIT}
        aria-label={t("newTab")}
        title={t("newTab")}
        className="hover:bg-muted rounded-md p-2 disabled:opacity-40"
      >
        <Plus className="size-4" aria-hidden />
      </button>
      <Popover open={historyOpen} onOpenChange={setHistoryOpen}>
        <PopoverTrigger asChild>
          <button
            aria-label={t("history")}
            title={t("history")}
            className="hover:bg-muted rounded-md p-2"
          >
            <History className="size-4" aria-hidden />
          </button>
        </PopoverTrigger>
        <PopoverContent
          align="end"
          className="w-80 space-y-2 p-2"
          onOpenAutoFocus={(event) => event.preventDefault()}
        >
          <SearchInput
            value={search}
            onChange={setSearch}
            placeholder={t("searchHistory")}
            className="w-full sm:w-full"
          />
          <div className="max-h-56 space-y-1 overflow-y-auto">
            {history.isPending ? (
              <p role="status" className="p-3 text-xs">
                {t("loadingHistory")}
              </p>
            ) : history.isError ? (
              <button onClick={() => void history.refetch()} className="w-full p-3 text-xs">
                {t("retryHistory")}
              </button>
            ) : !history.data?.items.length ? (
              <p className="text-muted-foreground p-3 text-xs">{t("emptyHistory")}</p>
            ) : (
              history.data.items.map((conversation) => (
                <button
                  key={conversation.id}
                  onClick={() => open(conversation)}
                  className="hover:bg-muted w-full truncate rounded-md px-3 py-2 text-start text-sm"
                >
                  {conversation.title || t("newConversation")}
                </button>
              ))
            )}
          </div>
        </PopoverContent>
      </Popover>
      <button
        onClick={() => {
          void newQuickAskWindow().catch((error: unknown) => {
            reportShellFailure("opening another Quick Ask window", error);
            toast.error(t("windowFailed"));
          });
        }}
        aria-label={t("newWindow")}
        title={t("newWindow")}
        className="hover:bg-muted rounded-md p-2"
      >
        <PanelsTopLeft className="size-4" aria-hidden />
      </button>
    </div>
  );
  return (
    <>
      {tabs.map((tab) => (
        <div
          key={tab.key}
          role="tabpanel"
          id={`panel-${tab.key}`}
          aria-labelledby={`tab-${tab.key}`}
          hidden={active !== tab.key}
        >
          <ChatScope agentId={tab.agentId}>
            <TabContent
              tab={tab}
              active={active === tab.key}
              toolbar={active === tab.key ? toolbar : undefined}
              historyOpen={historyOpen}
              onNew={() => open()}
              newDisabled={tabs.length >= LIMIT}
              update={update}
            />
          </ChatScope>
        </div>
      ))}
    </>
  );
}
function TabContent({
  tab,
  active,
  toolbar,
  onNew,
  historyOpen,
  newDisabled,
  update,
}: {
  tab: Tab;
  active: boolean;
  toolbar: React.ReactNode;
  onNew: () => void;
  historyOpen: boolean;
  newDisabled: boolean;
  update: (key: string, state: QuickAskTabState) => void;
}) {
  const onState = useCallback(
    (state: QuickAskTabState) => update(tab.key, state),
    [tab.key, update],
  );
  return (
    <>
      <QuickAsk
        active={active}
        initialConversationId={tab.initialId}
        toolbar={toolbar}
        historyControl={tab.initialId ? <RestoreQuickAsk id={tab.initialId} /> : undefined}
        minWindowHeight={historyOpen ? 560 : 64}
        onNewConversation={onNew}
        newDisabled={newDisabled}
        onTabState={onState}
      />
    </>
  );
}
