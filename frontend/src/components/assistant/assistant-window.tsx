"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { flushSync } from "react-dom";
import { Bell, BellOff, Camera, History, MessageSquarePlus, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { AgentPicker } from "@/components/chat/agent-picker";
import { ChatContainer, type ChatPrompt } from "@/components/chat/chat-container";
import type { IncomingFiles } from "@/components/chat/chat-input";
import { useAgents } from "@/hooks/use-agents";
import { useConversations } from "@/hooks/use-conversations";
import { recallConversation, rememberConversation } from "@/lib/architect-conversation";
import { consoleLink, type ConsoleLink } from "@/lib/assistant-highlight";
import { captureThisTab } from "@/lib/assistant-screenshot";
import type { AssistantPageContext } from "@/lib/assistant-page-context";
import { cn } from "@/lib/utils";
import { useAgentSelectionStore, useAuthStore, useOrgStore } from "@/stores";
import type { AssistantState } from "@/types/assistant";

import { AssistantHistory } from "./assistant-history";
import { architectName, AssistantFace, WINDOW_CLASSES } from "./assistant-launcher";
import { AssistantWelcome } from "./assistant-welcome";
import { AssistantPageContextBar } from "./assistant-page-context";

interface AssistantWindowProps {
  assistant: AssistantState;
  agentId: string;
  open: boolean;
  /** A prompt a bubble asked, sent as the reader. */
  prompt: ChatPrompt | null;
  /** Words written into the message box for the reader to send, once per id. */
  draft?: { id: number; text: string } | null;
  /** The current registered page, shown before it accompanies a question. */
  page: AssistantPageContext;
  getPageContext: () => AssistantPageContext;
  tipsOff: boolean;
  onTipsOff: (off: boolean) => void;
  /** Hide the window, or show it again; the conversation stays. */
  onOpenChange: (open: boolean) => void;
  /** A console page the Architect linked to was opened. */
  onConsoleLink: (link: ConsoleLink) => void;
}

/**
 * The floating chat starts with the AI Architect and can be handed to another
 * permitted agent. Its `ChatScope` stays mounted when the answerer changes, so
 * the transcript stays and none of its state is the main chat's.
 */
export function AssistantWindow({
  assistant,
  agentId,
  open,
  prompt,
  draft = null,
  page,
  getPageContext,
  tipsOff,
  onTipsOff,
  onOpenChange,
  onConsoleLink,
}: AssistantWindowProps) {
  const t = useTranslations("assistantWidget");
  const tPicker = useTranslations("chat.agentPicker");
  const selectedAgentId = useAgentSelectionStore((state) => state.selectedAgentId);
  const { agents, isLoading, isFetching, error, refetch } = useAgents({ includeArchived: true });
  const selected = agents.find((agent) => agent.id === selectedAgentId);
  const canSend = selected?.status === "published" && selected.can_run === true;
  const isMainAgent = selectedAgentId === agentId;
  const name = isMainAgent
    ? architectName(assistant, t("defaultName"))
    : (selected?.name ?? tPicker("noneSelected"));
  const { startNewChat, selectConversation, currentConversationId } = useConversations({
    agentId: selectedAgentId,
  });
  const userId = useAuthStore((state) => state.user?.id);
  const organizationId = useOrgStore((state) => state.activeOrgId);
  const restored = useRef(false);
  useEffect(() => {
    if (restored.current || !userId || !organizationId) return;
    restored.current = true;
    const last = recallConversation(userId, organizationId);
    if (last && !currentConversationId) void selectConversation(last);
  }, [userId, organizationId, currentConversationId, selectConversation]);
  useEffect(() => {
    if (userId && organizationId && currentConversationId)
      rememberConversation(userId, organizationId, currentConversationId);
  }, [userId, organizationId, currentConversationId]);
  const startAfresh = () => {
    if (userId && organizationId) rememberConversation(userId, organizationId, null);
    void startNewChat();
  };
  const [showHistory, setShowHistory] = useState(false);
  const [incoming, setIncoming] = useState<IncomingFiles | null>(null);
  const [includePage, setIncludePage] = useState(true);
  const [wroteDraft, setWroteDraft] = useState<number | null>(null);
  if (draft !== null && wroteDraft !== draft.id) {
    setWroteDraft(draft.id);
    setIncoming((last) => ({ id: (last?.id ?? 0) + 1, files: [], text: draft.text }));
  }
  const pageContext = useCallback(
    () => (includePage ? getPageContext() : null),
    [includePage, getPageContext],
  );

  // /assistant can install and publish after another surface cached the list.
  // Refresh that stale registry once; an explicit permission refusal stays put.
  const registryRefreshAttempt = useRef<string | null>(null);
  useEffect(() => {
    if (
      !open ||
      assistant.status !== "ready" ||
      selectedAgentId !== agentId ||
      isLoading ||
      isFetching ||
      error ||
      selected?.status === "published" ||
      registryRefreshAttempt.current === agentId
    )
      return;
    registryRefreshAttempt.current = agentId;
    void refetch();
  }, [
    open,
    assistant.status,
    selectedAgentId,
    agentId,
    isLoading,
    isFetching,
    error,
    selected?.status,
    refetch,
  ]);

  // The window steps aside while the page is photographed, so the screenshot
  // shows the page rather than the conversation about it.
  const screenshot = async () => {
    // Committed before the capture starts, or the first frame still has it.
    flushSync(() => onOpenChange(false));
    try {
      const file = await captureThisTab();
      if (file) setIncoming((last) => ({ id: (last?.id ?? 0) + 1, files: [file] }));
    } catch {
      toast.error(t("screenshotFailed"));
    } finally {
      onOpenChange(true);
    }
  };

  const toggleTips = () => {
    onTipsOff(!tipsOff);
    toast(tipsOff ? t("tipsOnDone") : t("tipsOffDone"));
  };

  // "Show me where": a console link in the conversation opens the page behind
  // the window rather than navigating away from it.
  const onClickCapture = (event: React.MouseEvent) => {
    const anchor = (event.target as Element).closest("a");
    const link = consoleLink(anchor?.getAttribute("href") ?? null, window.location.origin);
    if (link === null) return;
    event.preventDefault();
    onConsoleLink(link);
  };

  return (
    <div
      role="dialog"
      data-assistant-window
      aria-label={name}
      className={cn(WINDOW_CLASSES, !open && "hidden")}
    >
      <header className="border-border flex min-w-0 items-center gap-2 border-b px-3 py-2">
        <div
          data-tour="assistant-agent-picker"
          className="flex min-w-0 flex-1 [&>button]:max-w-full"
        >
          <AgentPicker
            followUrl={false}
            includeWorkflows={false}
            allowDefault={false}
            autoSelect={false}
            selectedLabel={isMainAgent ? name : undefined}
          />
        </div>
        <HeaderButton label={t("screenshot")} onClick={() => void screenshot()}>
          <Camera className="h-4 w-4" />
        </HeaderButton>
        <HeaderButton
          label={t("history")}
          pressed={showHistory}
          disabled={selectedAgentId === null}
          onClick={() => setShowHistory((shown) => !shown)}
        >
          <History className="h-4 w-4" />
        </HeaderButton>
        <HeaderButton
          label={t("newConversation")}
          onClick={() => {
            setShowHistory(false);
            startAfresh();
          }}
        >
          <MessageSquarePlus className="h-4 w-4" />
        </HeaderButton>
        <HeaderButton
          label={tipsOff ? t("tipsOn") : t("tipsOff")}
          pressed={tipsOff}
          onClick={toggleTips}
        >
          {tipsOff ? <BellOff className="h-4 w-4" /> : <Bell className="h-4 w-4" />}
        </HeaderButton>
        <HeaderButton label={t("close")} onClick={() => onOpenChange(false)}>
          <X className="h-4 w-4" />
        </HeaderButton>
      </header>
      <AssistantPageContextBar page={page} enabled={includePage} onEnabledChange={setIncludePage} />
      <div className="relative flex min-h-0 flex-1" onClickCapture={onClickCapture}>
        {showHistory && selectedAgentId && (
          <AssistantHistory
            agentId={selectedAgentId}
            onClose={() => setShowHistory(false)}
            onNew={() => {
              setShowHistory(false);
              startAfresh();
            }}
          />
        )}
        <div className="flex min-w-0 flex-1 flex-col">
          <ChatContainer
            prompt={prompt}
            agentFixed
            sendDisabled={!canSend}
            pageContext={pageContext}
            incomingFiles={incoming}
            emptyState={
              isMainAgent
                ? (onPick) => (
                    <AssistantWelcome
                      setup={
                        assistant.status === "needs_model"
                          ? { agentId, canConfigure: assistant.can_configure }
                          : undefined
                      }
                      greeting={assistant.greeting}
                      name={name}
                      mark={<AssistantFace assistant={assistant} agentId={agentId} size="lg" />}
                      page={includePage ? page : null}
                      onPick={onPick}
                    />
                  )
                : undefined
            }
          />
        </div>
      </div>
    </div>
  );
}

function HeaderButton({
  label,
  onClick,
  pressed,
  disabled,
  children,
}: {
  label: string;
  onClick: () => void;
  pressed?: boolean;
  disabled?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      aria-pressed={pressed}
      disabled={disabled}
      onClick={onClick}
      className="text-muted-foreground hover:text-foreground hover:bg-foreground/[0.05] aria-pressed:text-foreground aria-pressed:bg-foreground/[0.06] shrink-0 rounded-md p-1.5 disabled:opacity-50"
    >
      {children}
    </button>
  );
}
