"use client";

import { useEffect, useRef, useState } from "react";
import { flushSync } from "react-dom";
import { Bell, BellOff, Camera, History, MessageSquarePlus, X } from "lucide-react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";

import { ChatContainer, type ChatPrompt } from "@/components/chat/chat-container";
import type { IncomingFiles } from "@/components/chat/chat-input";
import { useConversations } from "@/hooks/use-conversations";
import { recallConversation, rememberConversation } from "@/lib/architect-conversation";
import { consoleLink, type ConsoleLink } from "@/lib/assistant-highlight";
import { captureThisTab } from "@/lib/assistant-screenshot";
import { cn } from "@/lib/utils";
import { useAuthStore, useOrgStore } from "@/stores";
import type { AssistantState } from "@/types/assistant";

import { AssistantHistory } from "./assistant-history";
import { architectName, AssistantFace, WINDOW_CLASSES } from "./assistant-launcher";
import { AssistantWelcome, type PageContext } from "./assistant-welcome";

interface AssistantWindowProps {
  assistant: AssistantState;
  agentId: string;
  open: boolean;
  /** A prompt a bubble asked, sent as the reader. */
  prompt: ChatPrompt | null;
  /** The page behind the window, for "What am I looking at?". */
  page: PageContext;
  tipsOff: boolean;
  onTipsOff: (off: boolean) => void;
  /** Hide the window, or show it again; the conversation stays. */
  onOpenChange: (open: boolean) => void;
  /** A console page the Architect linked to was opened. */
  onConsoleLink: (link: ConsoleLink) => void;
}

/**
 * The AI Architect's window (#2063): the console's own chat, addressed to the
 * assistant, in a `ChatScope` the widget gives it - so it is the same component
 * as `/chat` and none of its state is the main chat's.
 */
export function AssistantWindow({
  assistant,
  agentId,
  open,
  prompt,
  page,
  tipsOff,
  onTipsOff,
  onOpenChange,
  onConsoleLink,
}: AssistantWindowProps) {
  const t = useTranslations("assistantWidget");
  const { startNewChat, selectConversation, currentConversationId } = useConversations({
    agentId,
  });
  const userId = useAuthStore((state) => state.user?.id);
  const organizationId = useOrgStore((state) => state.activeOrgId);
  const restored = useRef(false);
  // A page load goes back to the conversation last open here; only New conversation starts one.
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
  const name = architectName(assistant, t("defaultName"));

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
      <header className="border-border flex items-center gap-2 border-b px-3 py-2">
        <AssistantFace assistant={assistant} agentId={agentId} size="sm" />
        <p className="min-w-0 flex-1 truncate text-sm font-semibold">{name}</p>
        <HeaderButton label={t("screenshot")} onClick={() => void screenshot()}>
          <Camera className="h-4 w-4" />
        </HeaderButton>
        <HeaderButton
          label={t("history")}
          pressed={showHistory}
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
      <div className="relative flex min-h-0 flex-1" onClickCapture={onClickCapture}>
        {showHistory && (
          <AssistantHistory
            agentId={agentId}
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
            incomingFiles={incoming}
            emptyState={(onPick) => (
              <AssistantWelcome
                greeting={assistant.greeting}
                name={name}
                mark={<AssistantFace assistant={assistant} agentId={agentId} size="lg" />}
                page={page}
                onPick={onPick}
              />
            )}
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
  children,
}: {
  label: string;
  onClick: () => void;
  pressed?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      aria-label={label}
      title={label}
      aria-pressed={pressed}
      onClick={onClick}
      className="text-muted-foreground hover:text-foreground hover:bg-foreground/[0.05] aria-pressed:text-foreground aria-pressed:bg-foreground/[0.06] rounded-md p-1.5"
    >
      {children}
    </button>
  );
}
