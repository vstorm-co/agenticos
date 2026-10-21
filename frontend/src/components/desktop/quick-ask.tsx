"use client";

import { useEffect, useRef, useState, type KeyboardEvent } from "react";
import { useTranslations } from "next-intl";
import { ArrowUpRight, CornerDownLeft, Loader2, Mic } from "lucide-react";

import { AgentPicker } from "@/components/chat/agent-picker";
import { MarkdownContent } from "@/components/chat/markdown-content";
import { useAgentDictation } from "@/hooks/use-agent-dictation";
import { useAuth } from "@/hooks/use-auth";
import { useChanged } from "@/hooks/use-changed";
import { useChat } from "@/hooks/use-chat";
import { useShellEvent } from "@/hooks/use-desktop";
import { hideQuickAsk, openInConsole, resizeQuickAsk, showConsole } from "@/lib/desktop/commands";
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
 * Push to talk: while its shortcut is held the panel records for the selected
 * agent, and on release the words are written into the question - the agent's
 * own dictation, as the composer's microphone records it.
 */
export function QuickAsk() {
  const t = useTranslations("desktop.quickAsk");
  const { isAuthenticated, isLoading } = useAuth();
  const [conversationId, setConversationId] = useState<string | null>(null);
  const [question, setQuestion] = useState("");
  const input = useRef<HTMLTextAreaElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const { messages, isProcessing, sendMessage, clearMessages } = useChat({
    conversationId,
    onConversationCreated: setConversationId,
  });
  const answer = [...messages].reverse().find((message) => message.role === "assistant");
  const asked = messages.some((message) => message.role === "user");
  const signedOut = !isLoading && !isAuthenticated;

  const selectedAgentId = useAgentSelectionStore((state) => state.selectedAgentId);
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

  // The panel was summoned: the question field is where the hands go.
  useShellEvent(SHELL_EVENTS.quickAsk, () => {
    input.current?.focus();
    input.current?.select();
  });

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

  const startOver = () => {
    clearMessages();
    setConversationId(null);
    setQuestion("");
  };

  const onKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
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
      if (!text || isProcessing) return;
      sendMessage(text);
      setQuestion("");
    } else if (event.key.toLowerCase() === "n" && command) {
      event.preventDefault();
      startOver();
    }
  };

  const listening = phase === "requesting" || phase === "recording";

  return (
    <div
      ref={panel}
      className="quick-ask-panel flex max-h-[560px] flex-col"
      data-tauri-drag-region="deep"
    >
      <div className="flex items-start gap-2 px-3 py-3">
        {signedOut ? null : <AgentPicker />}
        <textarea
          ref={input}
          rows={1}
          value={question}
          disabled={signedOut}
          onChange={(event) => {
            setQuestion(event.target.value);
            setNoDictation(false);
          }}
          onKeyDown={onKeyDown}
          placeholder={signedOut ? t("signedOut") : t("placeholder")}
          aria-label={t("placeholder")}
          className="text-foreground placeholder:text-muted-foreground field-sizing-content max-h-32 min-h-9 flex-1 resize-none bg-transparent py-1.5 text-base outline-none"
        />
        {listening ? (
          <Mic className="text-destructive mt-2 size-4 animate-pulse" aria-label={t("listening")} />
        ) : null}
        {isProcessing ? (
          <Loader2
            className="text-muted-foreground mt-2 size-4 animate-spin"
            aria-label={t("thinking")}
          />
        ) : null}
      </div>
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
      {asked ? (
        <>
          <div className="border-border min-h-0 flex-1 overflow-y-auto border-t px-4 py-3 text-sm">
            {answer?.content ? (
              <MarkdownContent content={answer.content} streaming={answer.isStreaming} />
            ) : (
              <p className="text-muted-foreground">{t("thinking")}</p>
            )}
          </div>
          <div className="border-border text-muted-foreground flex items-center justify-between gap-3 border-t px-4 py-2 text-xs">
            <span>
              {t.rich("close", { kbd: (chunks) => <kbd className="font-mono">{chunks}</kbd> })}
            </span>
            <button
              type="button"
              disabled={!conversationId}
              onClick={openConversation}
              className="hover:text-foreground flex items-center gap-1 disabled:opacity-50"
            >
              <CornerDownLeft className="size-3" aria-hidden />
              {t("continueInConsole")}
              <ArrowUpRight className="size-3" aria-hidden />
            </button>
          </div>
        </>
      ) : null}
    </div>
  );
}
