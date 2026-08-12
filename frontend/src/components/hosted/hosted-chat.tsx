"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { MessageSquarePlus, Mic, MicOff, Send } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button, Input } from "@/components/ui";
import { WS_URL } from "@/lib/constants";
import { cn } from "@/lib/utils";
import type { HostedPageConfig } from "@/types/hosted";

/** One line of the thread, as the page has it. */
interface Turn {
  role: "user" | "assistant";
  text: string;
}

/**
 * Where a returning visitor's identity is kept, per public key.
 *
 * Per key rather than one for the whole browser: two hosted pages are two
 * conversations with two different agents, and a shared id would put them in the
 * same thread on the server.
 */
function visitorKeyFor(publicKey: string): string {
  const existing = window.localStorage.getItem(storageKeyFor(publicKey));
  return existing || mintVisitorKey(publicKey);
}

function storageKeyFor(publicKey: string): string {
  return `agenticos:visitor:${publicKey}`;
}

/**
 * A fresh key, replacing whatever was stored.
 *
 * What "start a new chat" means here: the server maps a key to a conversation,
 * so a new key is a new thread. The old one is not deleted - it stops being the
 * one this browser resumes, which is the honest description and the one the
 * Builder's hint gives.
 */
function mintVisitorKey(publicKey: string): string {
  const bytes = new Uint8Array(16);
  window.crypto.getRandomValues(bytes);
  const minted = Array.from(bytes, (byte) => byte.toString(16).padStart(2, "0")).join("");
  window.localStorage.setItem(storageKeyFor(publicKey), minted);
  return minted;
}

/**
 * What this visitor's own URL says about them, for the variables that allow it.
 *
 * Read from `?var_<name>=` and filtered to the declared, URL-safe set the server
 * sent - the server drops anything else regardless, so this only avoids sending
 * values that would be thrown away.
 */
function suppliedFromUrl(allowed: string[]): Record<string, string> {
  if (allowed.length === 0) return {};
  const params = new URLSearchParams(window.location.search);
  const supplied: Record<string, string> = {};
  for (const name of allowed) {
    const value = params.get(`var_${name}`);
    if (value !== null) supplied[name] = value;
  }
  return supplied;
}

/**
 * A published agent, reached by a link and nothing else.
 *
 * A plainer `/chat`: the thread, the composer and the streamed answer. No agent
 * picker, no conversation list, no tool panels and no approvals queue - those are
 * all about being a member of an organization, and nobody here is.
 *
 * It speaks the widget's socket unchanged, so there is no second protocol to keep
 * in step: `ready`, `history`, `typing`, `message`, `error` in, one `message`
 * frame out. `4029` is the rate limit and worth telling somebody about; every
 * other close is the same refusal the widget gets, and says as little.
 *
 * What it offers beyond that is the operator's to decide, and arrives in the
 * config rather than being assumed here: a capability the page turned on for
 * itself would be one nobody could turn off.
 */
export function HostedChat({ config }: { config: HostedPageConfig }) {
  const t = useTranslations("hosted");
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState("");
  const [thinking, setThinking] = useState(false);
  const [closed, setClosed] = useState<"refused" | "too-many" | null>(null);
  // Bumped to reconnect on a fresh key. The socket carries the key in its URL,
  // so a new thread is a new connection rather than a frame.
  const [session, setSession] = useState(0);
  const [listening, setListening] = useState(false);
  // Whether this browser has a recogniser at all. Read in an effect because it
  // is a browser fact and the first render is the server's: a control that
  // cannot work is not rendered, which is the same rule the dashboard applies to
  // a permission somebody lacks.
  const [canDictate, setCanDictate] = useState(false);
  const socketRef = useRef<WebSocket | null>(null);
  const threadRef = useRef<HTMLDivElement | null>(null);
  const recognitionRef = useRef<SpeechRecognition | null>(null);

  useEffect(() => {
    const visitor = visitorKeyFor(config.public_key);
    const url = `${WS_URL}/api/v1/embed/${encodeURIComponent(config.public_key)}/ws?visitor=${visitor}`;
    const socket = new WebSocket(url);
    socketRef.current = socket;

    socket.onmessage = (event) => {
      const frame = JSON.parse(event.data as string);
      if (frame.type === "history") {
        setTurns(frame.messages as Turn[]);
      }
      if (frame.type === "typing") {
        setThinking(true);
      }
      if (frame.type === "message") {
        setThinking(false);
        setTurns((said) => [...said, { role: "assistant", text: frame.text as string }]);
      }
      if (frame.type === "error") {
        setThinking(false);
        setTurns((said) => [...said, { role: "assistant", text: frame.message as string }]);
      }
    };
    socket.onclose = (event) => {
      setThinking(false);
      if (event.code === 4029) setClosed("too-many");
      else if (event.code === 4003) setClosed("refused");
    };

    return () => socket.close();
  }, [config.public_key, session]);

  useEffect(() => {
    setCanDictate(Boolean(window.SpeechRecognition || window.webkitSpeechRecognition));
  }, []);

  useEffect(() => {
    const thread = threadRef.current;
    if (thread !== null) thread.scrollTop = thread.scrollHeight;
  }, [turns, thinking]);

  const startFresh = useCallback(() => {
    mintVisitorKey(config.public_key);
    setTurns([]);
    setThinking(false);
    setClosed(null);
    setSession((count) => count + 1);
  }, [config.public_key]);

  /**
   * Dictate into the box using the browser's own recogniser.
   *
   * Nothing is sent anywhere by us: the transcript arrives as text and lands in
   * the draft, exactly as if it had been typed. A browser that has no recogniser
   * says so rather than presenting a button that does nothing - the API is
   * prefixed in most of them and absent in some.
   */
  const toggleDictation = useCallback(() => {
    if (listening) {
      recognitionRef.current?.stop();
      return;
    }
    const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!Recognition) return;
    const recognition = new Recognition();
    recognition.continuous = true;
    recognition.interimResults = false;
    recognition.lang = navigator.language || "en-US";
    recognition.onresult = (event: SpeechRecognitionEvent) => {
      let heard = "";
      for (let index = event.resultIndex; index < event.results.length; index += 1) {
        const result = event.results[index];
        if (result?.isFinal) heard += result[0]?.transcript ?? "";
      }
      if (heard) setDraft((current) => (current ? `${current} ${heard.trim()}` : heard.trim()));
    };
    recognition.onend = () => setListening(false);
    recognition.onerror = () => setListening(false);
    recognitionRef.current = recognition;
    recognition.start();
    setListening(true);
  }, [listening]);

  const send = useCallback(() => {
    const text = draft.trim();
    const socket = socketRef.current;
    if (!text || socket === null || socket.readyState !== WebSocket.OPEN) return;
    setTurns((said) => [...said, { role: "user", text }]);
    setDraft("");
    socket.send(
      JSON.stringify({ type: "message", text, context: suppliedFromUrl(config.variables) }),
    );
  }, [draft, config.variables]);

  return (
    <div className="mx-auto flex h-dvh max-w-3xl flex-col px-4">
      <header className="flex items-center gap-3 border-b py-4">
        {config.logo_url !== null && (
          // A plain `<img>`, not `next/image`: the file is served by the API,
          // whose host is not in `next.config` remote patterns - and must not have
          // to be for a self-hosted deployment to render its own logo.
          // eslint-disable-next-line @next/next/no-img-element
          <img src={config.logo_url} alt="" className="h-8 w-8 rounded-md object-cover" />
        )}
        <h1 className="flex-1 text-lg font-semibold">{config.title}</h1>
        {config.allow_new_conversation && (
          <Button variant="ghost" size="sm" onClick={startFresh}>
            <MessageSquarePlus className="h-4 w-4" />
            {t("newConversation")}
          </Button>
        )}
      </header>

      <div ref={threadRef} className="flex-1 space-y-3 overflow-y-auto py-4">
        {config.welcome !== "" && turns.length === 0 && (
          <p className="text-muted-foreground text-sm whitespace-pre-wrap">{config.welcome}</p>
        )}
        {turns.map((turn, index) => (
          <div
            key={index}
            className={cn("flex", turn.role === "user" ? "justify-end" : "justify-start")}
          >
            <div
              className={cn(
                "max-w-[80%] rounded-2xl px-4 py-2.5 text-sm whitespace-pre-wrap",
                turn.role === "user" ? "text-white" : "bg-muted",
              )}
              style={turn.role === "user" ? { background: config.accent } : undefined}
            >
              {turn.text}
            </div>
          </div>
        ))}
        {thinking && <p className="text-muted-foreground text-sm">{t("thinking")}</p>}
        {closed !== null && (
          <p className="text-muted-foreground text-sm">
            {closed === "too-many" ? t("tooManyConnections") : t("unavailable")}
          </p>
        )}
      </div>

      <form
        className="flex items-center gap-2 border-t py-4"
        onSubmit={(event) => {
          event.preventDefault();
          send();
        }}
      >
        <Input
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          placeholder={t("placeholder")}
          aria-label={t("placeholder")}
          disabled={closed !== null}
        />
        {config.allow_voice && canDictate && (
          <Button
            type="button"
            variant="ghost"
            size="icon"
            onClick={toggleDictation}
            disabled={closed !== null}
            aria-label={listening ? t("stopDictation") : t("startDictation")}
          >
            {listening ? (
              <MicOff className="text-destructive h-4 w-4 animate-pulse" />
            ) : (
              <Mic className="text-muted-foreground h-4 w-4" />
            )}
          </Button>
        )}
        <Button type="submit" disabled={closed !== null || draft.trim() === ""}>
          <Send className="h-4 w-4" />
          <span className="sr-only">{t("send")}</span>
        </Button>
      </form>
    </div>
  );
}
