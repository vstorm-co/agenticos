"use client";

import { useEffect, useId, useLayoutEffect, useRef, useState, type KeyboardEvent } from "react";
import { useTranslations } from "next-intl";
import {
  ArrowUpRight,
  ArrowUp,
  Plus,
  X,
  Clipboard,
  Files,
  Loader2,
  Mic,
  Quote,
  ShieldCheck,
  Square,
} from "lucide-react";

import { useConversationStore } from "@/stores";
import { useAuthStore } from "@/stores";
import { useTenantId } from "@/hooks/use-organizations";
import { MentionPalette } from "@/components/chat/mention-palette";
import { useMentionables } from "@/hooks/use-mentionables";
import {
  insertMention,
  matching,
  MAX_MENTIONS,
  mentionAt,
  stillMentioned,
  type MentionQuery,
} from "@/lib/mentions";
import type { Mentionable } from "@/types/mention";
import { AgentPicker } from "@/components/chat/agent-picker";
import { FilePreviewDialog } from "@/components/chat/file-preview-dialog";
import { SourcesPanel } from "@/components/chat/sources-panel";
import { BrowserPanel } from "@/components/chat/browser-panel";
import { MessageList } from "@/components/chat/message-list";
import { LiveBrowsesProvider } from "@/components/chat/browser-card";
import { ConversationVisualsProvider } from "@/components/chat/visual-panel";
import { ToolApprovalDialog } from "@/components/chat/tool-approval-dialog";
import { ConnectAccountPrompt } from "@/components/chat/connect-account-prompt";
import { PendingMessages } from "@/components/chat/pending-messages";
import { QuestionPrompt } from "@/components/ui";
import { useReaderScrolledUp } from "@/hooks/use-reader-scrolled-up";
import { useAgentDictation } from "@/hooks/use-agent-dictation";
import { useAuth } from "@/hooks/use-auth";
import { useChanged } from "@/hooks/use-changed";
import { useChat } from "@/hooks/use-chat";
import { useShellEvent } from "@/hooks/use-desktop";
import { publishDesktopActivity } from "@/lib/desktop/readiness";
import { hideQuickAsk, openInConsole, resizeQuickAsk, showConsole } from "@/lib/desktop/commands";
import {
  openAccessibilitySettings,
  parseActiveContext,
  takeContextFiles,
  withContext,
  type ActiveContext,
  type ContextPassage,
} from "@/lib/desktop/context";
import { uploadFile, type FileUploadResponse } from "@/lib/file-api";
import { cn } from "@/lib/utils";
import { reportShellFailure, SHELL_EVENTS } from "@/lib/desktop/shell";
import { useAgentSelectionStore } from "@/stores/agent-selection-store";

function run(what: string, command: () => Promise<void>) {
  command().catch((error: unknown) => reportShellFailure(what, error));
}

/**
 * Quick ask: a question to any agent from anywhere, in the floating panel the
 * desktop app opens on its global shortcut.
 *
 * It is the console's own chat - the same socket, the same agent picker, the
 * same conversation saved under your name - in a panel that grows with the
 * answer. Enter asks, ⌘↩ (Ctrl+Enter) carries the conversation into the
 * console, ⌘N starts over and Escape puts the panel away.
 *
 * What was in front when it opened - the text selected there, the clipboard,
 * the files selected in Finder - sits under the question as chips. The
 * selection and the files go with the question unless taken off; the
 * clipboard, which can hold anything, only when put on.
 *
 * Push to talk: while its shortcut is held the panel records for the selected
 * agent, and on release the words are written into the question - the agent's
 * own dictation, as the composer's microphone records it.
 */
export function QuickAsk() {
  const t = useTranslations("desktop.quickAsk");
  const account = useAuthStore((s) => s.user?.id);
  const tenant = useTenantId();
  const tInput = useTranslations("chat.input");
  const { isAuthenticated, isLoading } = useAuth();
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [question, setQuestion] = useState("");
  const input = useRef<HTMLTextAreaElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const scroller = useRef<HTMLDivElement>(null);
  const scrolledUp = useRef(false);
  useReaderScrolledUp(scroller, scrolledUp);
  const {
    messages,
    isProcessing,
    isConnected,
    isStopping,
    sendMessage,
    clearMessages,
    stopGeneration,
    browses,
    reportVisual,
    pendingApproval,
    sendResumeDecisions,
    pendingQuestions,
    sendAskUserResponses,
    pendingConnection,
    sendConnectionResponse,
    queuedMessages,
    cancelQueued,
    retryQueued,
    clearQueued,
  } = useChat({
    conversationId,
    onConversationCreated: setConversationId,
  });
  const asked = messages.some((message) => message.role === "user");
  const signedOut = !isLoading && !isAuthenticated;
  useEffect(() => {
    const node = scroller.current;
    if (node && !scrolledUp.current) node.scrollTop = node.scrollHeight;
  }, [messages, pendingApproval, pendingQuestions, pendingConnection, queuedMessages]);

  useEffect(() => {
    const entries =
      !signedOut && conversationId && (isProcessing || pendingQuestions?.length || pendingApproval)
        ? [
            {
              id: conversationId,
              title: pendingQuestions?.length ? t("needsAnswer") : t("thinking"),
              question: !!pendingQuestions?.length,
              path: `/chat?id=${conversationId}`,
              stop_conversation: conversationId,
            },
          ]
        : [];
    void publishDesktopActivity(entries, signedOut ? null : conversationId, {
      user: account,
      organization: tenant,
    }).catch((e: unknown) => reportShellFailure("publishing Quick Ask activity", e));
  }, [
    conversationId,
    isProcessing,
    pendingQuestions,
    pendingApproval,
    signedOut,
    account,
    tenant,
    t,
  ]);
  useEffect(
    () => () => {
      void publishDesktopActivity([], null).catch((e: unknown) =>
        reportShellFailure("clearing Quick Ask activity", e),
      );
    },
    [],
  );
  const selectedAgentId = useAgentSelectionStore((state) => state.selectedAgentId);
  const mentionMenuId = useId();
  const [picked, setPicked] = useState<Mentionable[]>([]);
  const [mentionQuery, setMentionQuery] = useState<MentionQuery | null>(null);
  const [mentionIndex, setMentionIndex] = useState(0);
  const offered = useMentionables(signedOut ? null : selectedAgentId);
  const matches =
    mentionQuery && selectedAgentId ? matching(offered.items, mentionQuery.query) : [];
  const mentions = stillMentioned(question, picked);
  const mentionOpen = !signedOut && mentionQuery !== null && selectedAgentId !== null;
  const caretAfterPick = useRef<number | null>(null);
  if (useChanged(selectedAgentId ?? "")) {
    if (picked.length) setPicked([]);
    if (mentionQuery) setMentionQuery(null);
  }
  if (useChanged(`${mentionQuery?.query ?? ""}|${matches.length}`)) setMentionIndex(0);
  useLayoutEffect(() => {
    if (caretAfterPick.current !== null) {
      input.current?.focus();
      input.current?.setSelectionRange(caretAfterPick.current, caretAfterPick.current);
      caretAfterPick.current = null;
    }
  }, [question]);
  const pickMention = (item: Mentionable) => {
    if (!mentionQuery) return;
    const known = mentions.some((one) => one.id === item.id && one.kind === item.kind);
    if (mentions.length >= MAX_MENTIONS && !known) return;
    const next = insertMention(question, mentionQuery, item);
    setQuestion(next.text);
    setPicked(known ? mentions : [...mentions, item]);
    caretAfterPick.current = next.caret;
    setMentionQuery(null);
  };

  const dictation = useAgentDictation(signedOut ? null : selectedAgentId);
  const phase = dictation.state.phase;
  const stopDictation = dictation.actions.stop;
  /** Whether the push-to-talk shortcut is down - a release can come before the microphone is open. */
  const held = useRef(false);
  const [noDictation, setNoDictation] = useState(false);
  useShellEvent(SHELL_EVENTS.dictate, (payload) => {
    if (payload === "start") {
      held.current = true;
      input.current?.focus();
      if (dictation.engine !== "server") setNoDictation(true);
      else if (phase === "idle") void dictation.actions.start();
    } else if (payload === "stop") {
      held.current = false;
      stopDictation();
    } else {
      reportShellFailure("an unknown push-to-talk state", payload);
    }
  });
  // Let go while the microphone was still being asked for: stop as it opens.
  useEffect(() => {
    if (phase === "recording" && !held.current) stopDictation();
  }, [phase, stopDictation]);
  // The words, once per transcript, after whatever is already typed.
  const transcript = dictation.state.transcript;
  if (useChanged(transcript?.id ?? null) && transcript !== null) {
    setQuestion((typed) =>
      typed.trim() ? `${typed.trimEnd()} ${transcript.text}` : transcript.text,
    );
  }

  // Built hidden, then shown on the shortcut: the question field is where the
  // hands go, on the first showing and every one after it.
  useEffect(() => {
    input.current?.focus();
  }, []);

  const [context, setContext] = useState<ActiveContext | null>(null);
  const [include, setInclude] = useState({ selection: false, clipboard: false, files: false });
  const [attaching, setAttaching] = useState(false);
  const [attachFailed, setAttachFailed] = useState(false);
  const toggle = (what: keyof typeof include) =>
    setInclude((current) => ({ ...current, [what]: !current[what] }));

  // The panel was summoned: the question field is where the hands go, and
  // what was in front a moment ago is offered beside it.
  useShellEvent(SHELL_EVENTS.quickAsk, (payload) => {
    input.current?.focus();
    input.current?.select();
    setAttachFailed(false);
    try {
      const found = parseActiveContext(payload);
      setContext(found);
      setInclude({
        selection: found.selection !== null,
        clipboard: false,
        files: found.files.length > 0,
      });
    } catch (error) {
      setContext(null);
      reportShellFailure("could not read what was in front", error);
    }
  });

  const source = context?.app
    ? context.window
      ? `${context.app} - ${context.window}`
      : context.app
    : t("context.anApp");

  const ask = async (text: string) => {
    if (
      signedOut ||
      !selectedAgentId ||
      isProcessing ||
      attaching ||
      phase === "requesting" ||
      phase === "recording" ||
      phase === "transcribing"
    )
      return;
    const passages: ContextPassage[] = [];
    if (context?.selection && include.selection) {
      passages.push({ heading: t("context.selectedIn", { source }), text: context.selection });
    }
    if (context?.clipboard && include.clipboard) {
      passages.push({ heading: t("context.fromClipboard"), text: context.clipboard });
    }
    let attached: FileUploadResponse[] = [];
    if (context && include.files && context.files.length > 0) {
      setAttaching(true);
      try {
        attached = await Promise.all((await takeContextFiles()).map(uploadFile));
      } catch (error) {
        // Asked without the files it was meant to carry is a different question.
        setAttachFailed(true);
        reportShellFailure("could not attach the selected files", error);
        return;
      } finally {
        setAttaching(false);
      }
    }
    const content = withContext(text, passages);
    const named = stillMentioned(text, picked);
    scrolledUp.current = false;
    if (named.length)
      sendMessage(
        content,
        attached.length ? attached.map((file) => file.id) : undefined,
        attached.length ? attached : undefined,
        named,
      );
    else if (attached.length)
      sendMessage(
        content,
        attached.map((file) => file.id),
        attached,
      );
    else sendMessage(content);
    setQuestion("");
    setPicked([]);
    setMentionQuery(null);
    setContext(null);
  };

  // The window is as tall as the panel, so the answer never scrolls a window
  // that has room to grow; the shell keeps it between the question row and a ceiling.
  useEffect(() => {
    const node = panel.current;
    /* v8 ignore next -- the panel renders unconditionally, so it is mounted by the time this runs */
    if (!node) return;
    const observer = new ResizeObserver(([entry]) => {
      if (entry)
        run("could not size quick ask", () => resizeQuickAsk(Math.ceil(entry.contentRect.height)));
    });
    observer.observe(node);
    return () => observer.disconnect();
  }, []);

  const openConversation = () => {
    if (!conversationId) return;
    run("could not open the conversation", () => openInConsole(`/chat?id=${conversationId}`));
    run("could not put quick ask away", hideQuickAsk);
  };

  const resetConversation = useConversationStore((s) => s.reset);
  const startOver = () => {
    if (attaching || phase === "requesting" || phase === "recording" || phase === "transcribing")
      return;
    if (isProcessing && !conversationId) return;
    clearQueued();
    resetConversation();
    setContext(null);
    setAttachFailed(false);
    setNoDictation(false);
    stopDictation();
    setPicked([]);
    setMentionQuery(null);
    clearMessages();
    scrolledUp.current = false;
    setConversationId(null);
    setQuestion("");
    input.current?.focus();
  };

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.nativeEvent.isComposing) return;
    if (mentionOpen) {
      if (event.key === "Escape") {
        event.preventDefault();
        setMentionQuery(null);
        return;
      }
      if (matches.length && (event.key === "ArrowDown" || event.key === "ArrowUp")) {
        event.preventDefault();
        setMentionIndex(
          (index) =>
            (index + (event.key === "ArrowDown" ? 1 : -1) + matches.length) % matches.length,
        );
        return;
      }
      if (matches.length && (event.key === "Enter" || event.key === "Tab")) {
        event.preventDefault();
        const item = matches[mentionIndex];
        if (item) pickMention(item);
        return;
      }
    }

    const command = event.metaKey || event.ctrlKey;
    if (event.key === "Escape") {
      event.preventDefault();
      run("could not put quick ask away", hideQuickAsk);
    } else if (event.key === "Enter" && command) {
      event.preventDefault();
      openConversation();
    } else if (event.key === "Enter" && !event.shiftKey) {
      event.preventDefault();
      const text = question.trim();
      if (!text || isProcessing || attaching) return;
      void ask(text);
    } else if (event.key.toLowerCase() === "n" && command) {
      event.preventDefault();
      startOver();
    }
  };

  const listening = phase === "requesting" || phase === "recording";

  return (
    <div ref={panel} className="quick-ask-panel relative flex max-h-[560px] flex-col">
      <header className="flex shrink-0 items-center gap-2 px-3 py-2" data-tauri-drag-region="deep">
        <span className="text-muted-foreground mr-1 text-xs font-medium">{t("title")}</span>
        {!signedOut && <AgentPicker />}
        <div className="flex-1" />
        {!signedOut && (
          <button
            type="button"
            onClick={startOver}
            disabled={
              attaching ||
              listening ||
              phase === "transcribing" ||
              (isProcessing && !conversationId)
            }
            // i18n-exempt: WAI-ARIA machine-readable key combinations
            aria-keyshortcuts="Meta+N Control+N"
            title={t("newConversationHint")}
            className="text-muted-foreground hover:bg-muted hover:text-foreground focus-visible:ring-ring flex shrink-0 items-center gap-1 rounded-md px-2 py-1.5 text-xs outline-none focus-visible:ring-2 disabled:opacity-50"
          >
            <Plus className="size-3.5" aria-hidden />
            {t("newConversation")}
          </button>
        )}
        {asked && !signedOut && (
          <button
            type="button"
            disabled={!conversationId}
            onClick={openConversation}
            aria-label={t("continueInConsole")}
            title={t("continueInConsole")}
            className="text-muted-foreground hover:bg-muted hover:text-foreground focus-visible:ring-ring rounded-md p-2 outline-none focus-visible:ring-2 disabled:opacity-50"
          >
            <ArrowUpRight className="size-4" aria-hidden />
          </button>
        )}
        <button
          type="button"
          onClick={() => run("could not put quick ask away", hideQuickAsk)}
          aria-label={t("dismiss")}
          title={t("dismissHint")}
          className="text-muted-foreground hover:bg-muted hover:text-foreground focus-visible:ring-ring rounded-md p-2 outline-none focus-visible:ring-2"
        >
          <X className="size-4" aria-hidden />
        </button>
      </header>
      <div
        ref={scroller}
        hidden={(!asked && !(queuedMessages?.length > 0)) || signedOut}
        role="region"
        aria-label={t("conversation")}
        className="border-border min-h-0 flex-1 overflow-y-auto overscroll-contain border-t px-4 py-3 text-sm"
      >
        <LiveBrowsesProvider value={{ browses }}>
          <ConversationVisualsProvider
            messages={messages}
            conversationId={conversationId}
            onReport={reportVisual}
            onCompose={setQuestion}
            onSend={(text) => {
              if (!isProcessing) void ask(text);
            }}
          >
            <MessageList messages={messages} />
          </ConversationVisualsProvider>
        </LiveBrowsesProvider>
        {isProcessing &&
          !messages.some((message) => message.role === "assistant" && message.isStreaming) && (
            <p role="status" className="text-muted-foreground flex items-center gap-2 px-1 py-2">
              <Loader2 className="size-3.5 animate-spin" aria-hidden />
              {t("thinking")}
            </p>
          )}
        {queuedMessages?.length > 0 && (
          <PendingMessages
            messages={queuedMessages}
            onCancel={cancelQueued}
            onRetry={retryQueued}
            waitingForNetwork={!isConnected}
          />
        )}
        {pendingApproval && (
          <ToolApprovalDialog
            actionRequests={pendingApproval.actionRequests}
            reviewConfigs={pendingApproval.reviewConfigs}
            onDecisions={sendResumeDecisions}
            disabled={!isConnected || isStopping}
          />
        )}
        {pendingQuestions && pendingQuestions.length > 0 && (
          <QuestionPrompt
            questions={pendingQuestions}
            onComplete={sendAskUserResponses}
            disabled={!isConnected || isStopping}
          />
        )}
        {pendingConnection && (
          <ConnectAccountPrompt
            request={pendingConnection}
            onRespond={sendConnectionResponse}
            disabled={!isConnected || isStopping}
          />
        )}
      </div>

      <div className="focus-within:ring-ring/30 border-border bg-background/70 mx-3 mb-2 flex shrink-0 items-end gap-2 rounded-xl border px-3 py-2 focus-within:ring-2">
        <textarea
          ref={input}
          rows={1}
          value={question}
          disabled={signedOut}
          onChange={(event) => {
            setQuestion(event.target.value);
            setMentionQuery(mentionAt(event.target.value, event.target.selectionStart));
            setNoDictation(false);
          }}
          onClick={(event) =>
            setMentionQuery(
              mentionAt(event.currentTarget.value, event.currentTarget.selectionStart),
            )
          }
          aria-autocomplete="list"
          aria-controls={mentionOpen ? mentionMenuId : undefined}
          aria-activedescendant={
            mentionOpen && matches.length ? `${mentionMenuId}-${mentionIndex}` : undefined
          }
          onKeyDown={onKeyDown}
          placeholder={signedOut ? t("signedOut") : t("placeholder")}
          aria-label={t("placeholder")}
          className="text-foreground placeholder:text-muted-foreground field-sizing-content max-h-28 min-h-12 flex-1 resize-none bg-transparent py-1.5 text-base outline-none"
        />
        {listening ? (
          <Mic className="text-destructive mt-2 size-4 animate-pulse" aria-label={t("listening")} />
        ) : null}
        {isProcessing ? (
          <button
            type="button"
            onClick={stopGeneration}
            disabled={isStopping}
            aria-label={tInput("stopGenerating")}
            className="text-muted-foreground hover:bg-muted hover:text-foreground mb-1 rounded-md p-2 disabled:opacity-50"
          >
            <Square className="size-4" aria-hidden />
          </button>
        ) : (
          <button
            type="button"
            aria-label={tInput("send")}
            disabled={
              signedOut ||
              !selectedAgentId ||
              !question.trim() ||
              attaching ||
              listening ||
              phase === "transcribing"
            }
            onClick={() => {
              const text = question.trim();
              if (text && !attaching) void ask(text);
            }}
            className="bg-foreground text-background focus-visible:ring-ring mb-1 shrink-0 rounded-lg p-2 outline-none focus-visible:ring-2 disabled:opacity-30"
          >
            <ArrowUp className="size-4" aria-hidden />
          </button>
        )}
      </div>
      {!signedOut &&
        (!selectedAgentId || dictation.state.reason === "mic_denied" || noDictation) && (
          <button
            type="button"
            className="text-muted-foreground border-t px-4 py-2 text-left text-xs hover:underline"
            onClick={() =>
              run("opening feature setup", () =>
                openInConsole(
                  `/desktop/readiness?repair=${dictation.state.reason === "mic_denied" ? "microphone" : "agent"}`,
                ),
              )
            }
          >
            {t("repairSetup")}
          </button>
        )}
      {mentionOpen && (
        <div className="mx-3 mb-3">
          <MentionPalette
            id={mentionMenuId}
            placement="inline"
            items={matches}
            selectedIndex={mentionIndex}
            onSelectIndex={setMentionIndex}
            onPick={pickMention}
            isLoading={offered.isLoading}
            failed={offered.isError}
            full={mentions.length >= MAX_MENTIONS ? MAX_MENTIONS : undefined}
          />
        </div>
      )}
      {context && !signedOut ? (
        <ContextChips
          context={context}
          include={include}
          onToggle={toggle}
          onAllow={() => run("could not open the privacy settings", openAccessibilitySettings)}
        />
      ) : null}
      {attaching || attachFailed ? (
        <p role="status" className="border-border text-muted-foreground border-t px-4 py-2 text-xs">
          {attaching ? t("context.attaching") : t("context.attachFailed")}
        </p>
      ) : null}
      {listening || phase === "transcribing" || noDictation ? (
        <p role="status" className="border-border text-muted-foreground border-t px-4 py-2 text-xs">
          {noDictation ? t("noDictation") : listening ? t("listening") : t("transcribing")}
        </p>
      ) : null}
      {signedOut ? (
        <div className="border-border border-t px-4 py-3">
          <button
            type="button"
            onClick={() => run("could not bring the console forward", showConsole)}
            className="text-brand text-sm hover:underline"
          >
            {t("openConsole")}
          </button>
        </div>
      ) : null}

      {!signedOut && (
        <div className="text-muted-foreground flex shrink-0 items-center justify-between gap-3 px-4 pb-3 text-[11px]">
          <span>{t("sendHint")}</span>
          <span>{!isConnected ? t("offline") : t("mentionHint")}</span>
        </div>
      )}
      <FilePreviewDialog />
      <SourcesPanel contained />
      <BrowserPanel browses={browses} />
    </div>
  );
}

const CHIP =
  "flex max-w-full items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs transition-colors";

/** One chip per thing found in front: on, it goes with the question; off, it does not. */
function ContextChips({
  context,
  include,
  onToggle,
  onAllow,
}: {
  context: ActiveContext;
  include: { selection: boolean; clipboard: boolean; files: boolean };
  onToggle: (what: "selection" | "clipboard" | "files") => void;
  onAllow: () => void;
}) {
  const t = useTranslations("desktop.quickAsk.context");
  const chip = (on: boolean) =>
    cn(
      CHIP,
      on
        ? "bg-muted text-foreground border-transparent"
        : "text-muted-foreground border-dashed hover:text-foreground",
    );
  return (
    <div className="flex flex-wrap gap-1.5 px-3 pb-3">
      {context.selection ? (
        <button
          type="button"
          aria-pressed={include.selection}
          onClick={() => onToggle("selection")}
          title={context.selection}
          className={chip(include.selection)}
        >
          <Quote className="size-3 shrink-0" aria-hidden />
          <span className="truncate">{t("selection", { app: context.app ?? t("anApp") })}</span>
        </button>
      ) : null}
      {context.files.length > 0 ? (
        <button
          type="button"
          aria-pressed={include.files}
          onClick={() => onToggle("files")}
          title={context.files.join("\n")}
          className={chip(include.files)}
        >
          <Files className="size-3 shrink-0" aria-hidden />
          <span className="truncate">{t("files", { count: context.files.length })}</span>
        </button>
      ) : null}
      {context.clipboard ? (
        <button
          type="button"
          aria-pressed={include.clipboard}
          onClick={() => onToggle("clipboard")}
          title={context.clipboard}
          className={chip(include.clipboard)}
        >
          <Clipboard className="size-3 shrink-0" aria-hidden />
          <span className="truncate">{t("clipboard")}</span>
        </button>
      ) : null}
      {!context.accessibility && context.app ? (
        <button type="button" onClick={onAllow} className={chip(false)}>
          <ShieldCheck className="size-3 shrink-0" aria-hidden />
          <span className="truncate">{t("allow")}</span>
        </button>
      ) : null}
    </div>
  );
}
