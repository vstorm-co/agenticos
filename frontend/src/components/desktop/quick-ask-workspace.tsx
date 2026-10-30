"use client";
import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { History, X, Loader2, MessageSquare } from "lucide-react";
import { toast } from "sonner";
import { QuickAsk, type QuickAskTabState } from "./quick-ask";
import { RestoreQuickAsk, useQuickAskHistory } from "./quick-ask-history";
import { ChatScope } from "@/stores/chat-scope";
import { useAgentSelectionStore, useAuthStore } from "@/stores";
import { useTenantId } from "@/hooks/use-organizations";
import { SearchInput, useDebounced } from "@/components/ui";
import { ConversationAgents } from "@/components/agents/conversation-agents";
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
  useEffect(() => {
    if (!historyOpen) return;
    const closeHistory = (event: globalThis.KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      event.stopPropagation();
      setHistoryOpen(false);
    };
    window.addEventListener("keydown", closeHistory, true);
    return () => window.removeEventListener("keydown", closeHistory, true);
  }, [historyOpen]);
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
    <div className="border-border shrink-0 border-t">
      <div className="flex items-center gap-1 px-2 py-1.5">
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
          type="button"
          aria-label={t("history")}
          title={t("history")}
          aria-expanded={historyOpen}
          aria-controls="quick-ask-history"
          onClick={() => setHistoryOpen((open) => !open)}
          className="hover:bg-muted rounded-md p-2"
        >
          <History className="size-4" aria-hidden />
        </button>
      </div>
      {historyOpen && (
        <section
          id="quick-ask-history"
          aria-label={t("history")}
          className="border-border space-y-2 border-t p-2"
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
                  className="hover:bg-muted flex w-full items-center gap-3 rounded-lg px-2 py-2.5 text-start text-sm transition-colors"
                >
                  <ConversationAgents
                    agents={conversation.agents}
                    size="md"
                    showName={false}
                    className="shrink-0"
                  />
                  <span className="min-w-0 flex-1">
                    <span className="block truncate text-sm font-medium">
                      {conversation.title || t("newConversation")}
                    </span>
                    <span className="text-muted-foreground block truncate text-xs">
                      {conversation.agents?.map((agent) => agent.name).join(", ")}
                    </span>
                  </span>
                </button>
              ))
            )}
          </div>
        </section>
      )}
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
  newDisabled,
  update,
}: {
  tab: Tab;
  active: boolean;
  toolbar: React.ReactNode;
  onNew: () => void;
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
        onNewConversation={onNew}
        newDisabled={newDisabled}
        onTabState={onState}
      />
    </>
  );
}
