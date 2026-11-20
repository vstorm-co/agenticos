"use client";

import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { usePathname } from "next/navigation";

import type { ChatPrompt } from "@/components/chat/chat-container";
import { useShell } from "@/hooks/use-shell";
import { isDesktopShell } from "@/lib/desktop/shell";
import { useAssistant } from "@/hooks/use-assistant";
import { useAssistantPageContext } from "@/hooks/use-assistant-page-context";
import { useAssistantSignals } from "@/hooks/use-assistant-signals";
import { pointAt, type ConsoleLink } from "@/lib/assistant-highlight";
import {
  bubbleFor,
  isProactive,
  markRunSeen,
  pageOf,
  readPreferences,
  setBubblesOff,
  setDocked,
} from "@/lib/assistant-bubbles";
import { useRouter } from "@/lib/locale-navigation";
import { ChatScope, useAuthStore, useOrgStore } from "@/stores";
import { architectAskMatchesScope, useArchitectAskStore } from "@/stores/architect-ask-store";
import type { AssistantState } from "@/types/assistant";

import { AssistantBubble } from "./assistant-bubble";
import { architectName, AssistantLauncher, WidgetRoot } from "./assistant-launcher";
import { AssistantWindow } from "./assistant-window";

/** How long a page is looked at before the bubble speaks. */
const BUBBLE_DELAY_MS = 3000;

/** How long the button waits, untouched, before it tucks itself into the edge. */
export const DOCK_AFTER_MS = 45_000;

/** Where the window is full screen, and covers the page a link opens. */
const PHONE = "(max-width: 767px)";

/** Counts page views across the widget's life, for the occasional tip. */
let visits = 0;

/**
 * The AI Architect in the corner of every console page (#2063).
 *
 * A round button with the assistant's face, a speech bubble above it that speaks
 * to the page and to what is waiting, and a window holding the conversation.
 * Shown only to somebody who may run agents - the assistant is an agent like any
 * other. Before it has a model the same chat explains how to connect one.
 */
export function AssistantWidget({
  defaultAgentId,
  viewer = false,
}: { defaultAgentId?: string | null; viewer?: boolean } = {}) {
  // A failed read leaves the corner empty on every page rather than an error
  // following the reader around; Settings → Assistant is where it is said.
  const { assistant } = useAssistant();
  const userId = useAuthStore((state) => state.user?.id ?? null);
  const orgId = useOrgStore((state) => state.activeOrgId);
  if (!assistant || !assistant.can_use || assistant.agent_id === null) return null;
  if (assistant.status === "ready" || assistant.status === "needs_model") {
    return (
      <ReadyWidget
        key={JSON.stringify([userId, orgId, assistant.agent_id, defaultAgentId ?? null])}
        assistant={assistant}
        agentId={assistant.agent_id}
        defaultAgentId={defaultAgentId ?? assistant.agent_id}
        viewer={viewer}
      />
    );
  }
  return null;
}

const APPROVALS_HEARD_KEY = "assistant-approvals-heard";

/**
 * How many waiting approvals the bubble has raised in this tab.
 *
 * Kept for the tab rather than in memory: a link opened afresh reloads the
 * console, and the same sentence then followed the reader onto every page.
 */
function readApprovalsHeard(): number {
  try {
    return Number(sessionStorage.getItem(APPROVALS_HEARD_KEY)) || 0;
  } catch {
    return 0;
  }
}

function writeApprovalsHeard(count: number): void {
  try {
    sessionStorage.setItem(APPROVALS_HEARD_KEY, String(count));
  } catch {
    // Remembered for this page only.
  }
}

/** Whether the screen is a phone's, kept current as the window changes. */
function usePhone(): boolean {
  const [phone, setPhone] = useState(() => window.matchMedia(PHONE).matches);
  useEffect(() => {
    const query = window.matchMedia(PHONE);
    const update = () => setPhone(query.matches);
    query.addEventListener("change", update);
    return () => query.removeEventListener("change", update);
  }, []);
  return phone;
}

function ReadyWidget({
  assistant,
  agentId,
  defaultAgentId,
  viewer,
}: {
  assistant: AssistantState;
  agentId: string;
  defaultAgentId: string;
  viewer: boolean;
}) {
  const t = useTranslations("assistantWidget");
  const pathname = usePathname();
  const { page, getSnapshot } = useAssistantPageContext(pathname);
  const signals = useAssistantSignals();
  const organization = useOrgStore((state) => state.activeOrgId);
  const [open, setOpen] = useState(false);
  const [everOpened, setEverOpened] = useState(false);
  // The page the bubble has waited out its moment on; on any other it is quiet.
  const [readyOn, setReadyOn] = useState<string | null>(null);
  const [preferences, setPreferences] = useState(readPreferences);
  const shell = useShell();
  // Native Blobby already occupies the desktop corner. Keep the web assistant
  // available at the edge without covering card actions in the console.
  const docked = (isDesktopShell(shell) && shell.window === "main") || preferences.docked;
  // "Not now", or a bubble left to fade, on a page: quiet there for the rest
  // of this visit to the console.
  const [setAside, setSetAside] = useState<string | null>(null);
  // How many waiting approvals the bubble has already raised this visit. They
  // are not about the page, so once said they stay said on every page, until
  // more arrive - raised again on each navigation, the same sentence followed
  // the reader through the whole console.
  const [approvalsHeard, setApprovalsHeardState] = useState(readApprovalsHeard);
  const setApprovalsHeard = (count: number) => {
    setApprovalsHeardState(count);
    writeApprovalsHeard(count);
  };
  // A phone has no room for the bubble: a card over 40% of the screen, on
  // every page, hid the page it was talking about. There the button carries a
  // dot instead, and the window says the rest when it is opened.
  const phone = usePhone();
  const [prompt, setPrompt] = useState<ChatPrompt | null>(null);
  // Bumped by anything the reader does with the widget, which restarts the
  // wait before the button tucks itself away.
  const [touched, setTouched] = useState(0);
  const router = useRouter();

  const touch = useCallback(() => setTouched((count) => count + 1), []);

  const dock = useCallback((docked: boolean) => {
    setDocked(docked);
    setPreferences(readPreferences());
  }, []);

  // A new page gives the bubble a moment before it speaks.
  useEffect(() => {
    visits += 1;
    const timer = setTimeout(() => setReadyOn(pathname), BUBBLE_DELAY_MS);
    return () => clearTimeout(timer);
  }, [pathname]);

  // Left alone with the window closed, the button steps into the edge of the
  // screen; it stays there across pages and visits until it is pulled out.
  useEffect(() => {
    if (open || docked) return;
    const timer = setTimeout(() => dock(true), DOCK_AFTER_MS);
    return () => clearTimeout(timer);
  }, [open, docked, touched, dock]);

  const failedRun = signals.failedRunId !== preferences.seenRun ? signals.failedRunId : null;
  const bubble = bubbleFor(
    pathname,
    {
      stuck: signals.stuckIn !== null,
      pendingApprovals: signals.pendingApprovals > approvalsHeard ? signals.pendingApprovals : 0,
      failedRun: failedRun !== null,
      noAgents: signals.noAgents,
    },
    visits,
  );
  // Asking about a failed run, or waving it away, is hearing about it.
  const heard = () => {
    if (bubble === "failedRun" && failedRun !== null) markRunSeen(failedRun);
    if (bubble === "approvals") setApprovalsHeard(signals.pendingApprovals);
    setPreferences(readPreferences());
  };
  // The chat's composer takes the launcher's corner, so there the launcher steps
  // out - and a bubble pointing at a launcher that is not there is a message
  // floating over the composer with nothing to answer it from.
  const overComposer = pageOf(pathname).startsWith("/chat");
  const speaking =
    !phone &&
    !overComposer &&
    readyOn === pathname &&
    setAside !== pathname &&
    !open &&
    !docked &&
    bubble !== null &&
    !preferences.off &&
    !preferences.silenced.includes(pageOf(pathname));

  const openWindow = useCallback(() => {
    dock(false);
    setOpen(true);
    setEverOpened(true);
  }, [dock]);

  const [draft, setDraft] = useState<{ id: number; text: string } | null>(null);
  const ask = useCallback(
    (text: string, asDraft = false) => {
      openWindow();
      if (asDraft) setDraft((last) => ({ id: (last?.id ?? 0) + 1, text }));
      else setPrompt((last) => ({ id: (last?.id ?? 0) + 1, text }));
    },
    [openWindow],
  );

  // Asked from elsewhere in the console - "Make an agent of this" in a chat. Each
  // ask once: consume an external-store event, then check its account context at
  // delivery. A queued request is read after mounting; a switch cancels that delivery.
  useEffect(() => {
    let active = true;
    const consume = () => {
      if (!active) return;
      const { request, answered } = useArchitectAskStore.getState();
      if (!request) return;
      answered(request.id);
      if (
        architectAskMatchesScope(request, {
          userId: useAuthStore.getState().user?.id ?? null,
          orgId: useOrgStore.getState().activeOrgId,
        })
      )
        ask(request.text, request.draft);
    };
    const unsubscribe = useArchitectAskStore.subscribe(consume);
    void Promise.resolve().then(consume);
    return () => {
      active = false;
      unsubscribe();
    };
  }, [ask]);

  const followLink = (link: ConsoleLink) => {
    // On a phone the full-screen window steps aside so the page can be seen.
    if (window.matchMedia(PHONE).matches) setOpen(false);
    router.push(link.path);
    if (link.anchor) void pointAt(link.anchor, link.path);
  };

  return (
    <WidgetRoot>
      {everOpened && (
        // Keyed by organization: a switch starts the conversation afresh rather
        // than carrying one organization's thread into another.
        <ChatScope key={organization ?? "none"} agentId={defaultAgentId}>
          <AssistantWindow
            assistant={assistant}
            agentId={agentId}
            open={open}
            prompt={prompt}
            draft={draft}
            page={page}
            getPageContext={getSnapshot}
            tipsOff={preferences.off}
            onTipsOff={(off) => {
              setBubblesOff(off);
              setPreferences(readPreferences());
            }}
            onOpenChange={(next) => {
              setOpen(next);
              touch();
            }}
            onConsoleLink={followLink}
          />
        </ChatScope>
      )}

      {speaking && assistant.status === "needs_model" && (
        <button
          type="button"
          onClick={openWindow}
          className="bg-background border-border fixed right-4 bottom-24 z-50 max-w-[17rem] rounded-2xl border px-4 py-3 text-left text-sm shadow-lg md:right-6"
        >
          {t("setup.bubble")}
        </button>
      )}
      {speaking && assistant.status === "ready" && (
        <AssistantBubble
          bubble={bubble}
          values={{ run: failedRun ?? "", form: signals.stuckIn ?? "" }}
          proactive={isProactive(bubble)}
          onAsk={(text) => {
            heard();
            ask(text);
          }}
          onSilence={heard}
          onDismiss={() => {
            heard();
            setSetAside(pathname);
          }}
          onFade={() => {
            if (bubble === "approvals") setApprovalsHeard(signals.pendingApprovals);
            setSetAside(pathname);
          }}
          name={architectName(assistant, t("defaultName"))}
          path={pathname}
        />
      )}

      <AssistantLauncher
        assistant={assistant}
        agentId={agentId}
        viewer={viewer}
        open={open}
        docked={docked}
        waiting={(docked || phone) && bubble !== null && isProactive(bubble) && !preferences.off}
        onToggle={() => (open ? setOpen(false) : openWindow())}
        onHover={touch}
        overComposer={overComposer}
      />
    </WidgetRoot>
  );
}
