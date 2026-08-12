"use client";

import { useCallback, useEffect, useRef, useState, useSyncExternalStore } from "react";
import { MessageSquarePlus, Mic, MicOff, Paperclip, Send, X } from "lucide-react";
import { useTranslations } from "next-intl";

import { MarkdownContent } from "@/components/chat/markdown-content";
import { Button, Input } from "@/components/ui";
import { BACKEND_URL, WS_URL } from "@/lib/constants";
import { toolStep } from "@/lib/tool-steps";
import { cn } from "@/lib/utils";
import type { HostedPageConfig } from "@/types/hosted";

/** One tool call, as much of it as the operator lets this page see. */
interface Step {
  id: string;
  name: string;
  args?: Record<string, unknown>;
  result?: string;
}

/** One line of the thread, as the page has it. */
interface Turn {
  role: "user" | "assistant";
  text: string;
  thinking?: string;
  steps?: Step[];
  /**
   * Whether this turn is still being written.
   *
   * What makes a delta land on the turn it belongs to rather than starting a new
   * bubble per frame. Cleared by `complete`, which is the only frame that says a
   * turn is over.
   */
  live?: boolean;
}

/**
 * Fold one frame into the thread.
 *
 * Outside the component because it is the half worth testing on its own: the wire
 * is the dashboard's own vocabulary since #634, and what this page renders is
 * whatever of it the server chose to send. There is deliberately no branch here
 * that decides whether the reasoning or a step *may* be shown - a frame that
 * arrives is one the operator agreed to, and one they did not never left the
 * server (`EmbedSession._emit`).
 */
export function fold(said: readonly Turn[], type: string, data: Record<string, never>): Turn[] {
  const payload = data as Record<string, unknown>;
  switch (type) {
    case "history":
      return (payload.messages as Turn[]) ?? [];
    case "text_delta":
      return intoLive(said, (turn) => ({ ...turn, text: turn.text + String(payload.content) }));
    case "thinking_delta":
      return intoLive(said, (turn) => ({
        ...turn,
        thinking: (turn.thinking ?? "") + String(payload.content),
      }));
    case "tool_call":
      return intoLive(said, (turn) => ({
        ...turn,
        steps: [
          ...(turn.steps ?? []),
          {
            id: String(payload.tool_call_id),
            name: String(payload.tool_name),
            args: payload.args as Record<string, unknown> | undefined,
          },
        ],
      }));
    case "tool_result":
      return intoLive(said, (turn) => ({
        ...turn,
        steps: (turn.steps ?? []).map((step) =>
          step.id === payload.tool_call_id ? { ...step, result: String(payload.content) } : step,
        ),
      }));
    case "final_result":
      // What the run ended with. Assigned rather than appended: the deltas are the
      // same words, and a provider that streamed none leaves this as the only copy
      // of them. Empty on a turn that parked, which `error` then explains.
      return payload.output === ""
        ? [...said]
        : intoLive(said, (turn) => ({ ...turn, text: String(payload.output) }));
    case "complete":
      return said.map((turn) => (turn.live === true ? { ...turn, live: false } : turn));
    case "error":
      // A turn that produced nothing leaves an empty bubble behind, so the
      // refusal replaces it rather than appearing under it.
      return [
        ...withoutEmptyLive(said),
        { role: "assistant", text: String(payload.message) } as Turn,
      ];
    default:
      return [...said];
  }
}

function intoLive(said: readonly Turn[], mutate: (turn: Turn) => Turn): Turn[] {
  const last = said.at(-1);
  if (last !== undefined && last.role === "assistant" && last.live === true) {
    return [...said.slice(0, -1), mutate(last)];
  }
  return [...said, mutate({ role: "assistant", text: "", live: true })];
}

function withoutEmptyLive(said: readonly Turn[]): Turn[] {
  const last = said.at(-1);
  const empty =
    last !== undefined && last.live === true && last.text === "" && (last.steps ?? []).length === 0;
  return empty ? said.slice(0, -1) : [...said];
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
 * It speaks the same socket the widget does and the same frame vocabulary the
 * dashboard does, so there is no second protocol to keep in step: the answer
 * arrives as `text_delta`, the work as `tool_call` and `tool_result`, the
 * reasoning as `thinking_delta`, and `complete` says the turn is over. Which of
 * those arrive at all is the operator's decision, enforced where the frame is
 * *sent* - so there is no branch here that hides one. `4029` is the rate limit and
 * worth telling somebody about; every other close is the same refusal the widget
 * gets, and says as little.
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
  // Files already stored, waiting on the message that will name them. Held here
  // rather than sent as they arrive: the id is what the turn carries, and a file
  // attached and then thought better of should not become a turn of its own.
  const [attached, setAttached] = useState<{ id: string; filename: string }[]>([]);
  const [uploading, setUploading] = useState(false);
  // Whether this browser has a recogniser at all: a control that cannot work is
  // not rendered, the same rule the dashboard applies to a permission somebody
  // lacks. Read as an external snapshot rather than set from an effect - the
  // first render is the server's, where the answer is `false`, and an effect that
  // calls `setState` in its body renders the page twice for a fact that cannot
  // change while it is open. Nothing is subscribed to, so the store never
  // notifies.
  const canDictate = useSyncExternalStore(
    () => () => {},
    () => Boolean(window.SpeechRecognition || window.webkitSpeechRecognition),
    () => false,
  );
  const socketRef = useRef<WebSocket | null>(null);
  const threadRef = useRef<HTMLDivElement | null>(null);
  const recognitionRef = useRef<SpeechRecognition | null>(null);
  const filePicker = useRef<HTMLInputElement | null>(null);

  useEffect(() => {
    const visitor = visitorKeyFor(config.public_key);
    const url = `${WS_URL}/api/v1/embed/${encodeURIComponent(config.public_key)}/ws?visitor=${visitor}`;
    const socket = new WebSocket(url);
    socketRef.current = socket;

    socket.onmessage = (event) => {
      const frame = JSON.parse(event.data as string);
      if (frame.type === "model_request_start") setThinking(true);
      if (frame.type === "complete" || frame.type === "error") setThinking(false);
      setTurns((said) => fold(said, frame.type as string, frame.data ?? {}));
    };
    socket.onclose = (event) => {
      setThinking(false);
      if (event.code === 4029) setClosed("too-many");
      else if (event.code === 4003) setClosed("refused");
    };

    return () => socket.close();
  }, [config.public_key, session]);

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

  /**
   * Send a file, and keep the id the server answers with.
   *
   * Straight to the API rather than through a route handler of ours: this page has
   * no session to proxy, and the upload is authorised by the public key and the
   * visitor's own continuity key, both of which are already in the URL. A refusal
   * - too large, a type nothing can read, a page whose operator turned this off -
   * is said in the thread rather than thrown away, because a picker that appears
   * to do nothing is worse than a sentence.
   */
  const attach = useCallback(
    async (file: File) => {
      setUploading(true);
      try {
        const body = new FormData();
        body.append("file", file);
        const visitor = visitorKeyFor(config.public_key);
        const response = await fetch(
          `${BACKEND_URL}/api/v1/embed/${encodeURIComponent(config.public_key)}/files?visitor=${visitor}`,
          { method: "POST", body },
        );
        if (!response.ok) throw new Error("refused");
        const stored = (await response.json()) as { id: string; filename: string };
        setAttached((held) => [...held, stored]);
      } catch {
        setTurns((said) => [...said, { role: "assistant", text: t("uploadFailed") }]);
      } finally {
        setUploading(false);
      }
    },
    [config.public_key, t],
  );

  const send = useCallback(() => {
    const text = draft.trim();
    const socket = socketRef.current;
    if ((!text && attached.length === 0) || socket === null || socket.readyState !== WebSocket.OPEN)
      return;
    setTurns((said) => [...said, { role: "user", text }]);
    setDraft("");
    setAttached([]);
    socket.send(
      JSON.stringify({
        type: "message",
        text,
        file_ids: attached.map((file) => file.id),
        context: suppliedFromUrl(config.variables),
      }),
    );
  }, [draft, attached, config.variables]);

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
                "max-w-[80%] rounded-2xl px-4 py-2.5 text-sm",
                turn.role === "user" ? "text-white" : "bg-muted",
              )}
              style={turn.role === "user" ? { background: config.accent } : undefined}
            >
              {turn.thinking !== undefined && (
                <p className="text-muted-foreground mb-2 text-xs whitespace-pre-wrap italic">
                  {turn.thinking}
                </p>
              )}
              {(turn.steps ?? []).map((step) => (
                <ToolLine key={step.id} step={step} />
              ))}
              {/* Markdown for the agent, plain text for the visitor. An agent told
                  to answer in Markdown is answering in it whatever this page does
                  with the asterisks, which is the whole argument; what a visitor
                  typed is not a document and must not be reinterpreted as one. */}
              {turn.role === "assistant" ? (
                <MarkdownContent content={turn.text} />
              ) : (
                <span className="whitespace-pre-wrap">{turn.text}</span>
              )}
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

      {attached.length > 0 && (
        <div className="flex flex-wrap gap-2 pt-2">
          {attached.map((file) => (
            <span
              key={file.id}
              className="border-border flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-xs"
            >
              {file.filename}
              <button
                type="button"
                onClick={() => setAttached((held) => held.filter((one) => one.id !== file.id))}
                aria-label={t("removeAttachment", { name: file.filename })}
              >
                <X className="h-3 w-3" />
              </button>
            </span>
          ))}
        </div>
      )}

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
        {config.allow_files && (
          <>
            <input
              ref={filePicker}
              type="file"
              className="hidden"
              onChange={(event) => {
                const file = event.target.files?.[0];
                if (file) void attach(file);
                // Cleared so choosing the same file twice fires again, which is
                // what somebody does after a refused upload.
                event.target.value = "";
              }}
            />
            <Button
              type="button"
              variant="ghost"
              size="icon"
              disabled={closed !== null || uploading}
              onClick={() => filePicker.current?.click()}
              aria-label={t("attach")}
            >
              <Paperclip className="text-muted-foreground h-4 w-4" />
            </Button>
          </>
        )}
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
        <Button
          type="submit"
          disabled={closed !== null || (draft.trim() === "" && attached.length === 0)}
        >
          <Send className="h-4 w-4" />
          <span className="sr-only">{t("send")}</span>
        </Button>
      </form>
    </div>
  );
}

/**
 * One step of the agent's work, named the way the dashboard names it.
 *
 * Through `toolStep` and the catalog in `src/lib/tool-catalog.ts`, not a second
 * table of tool names: the last time that knowledge was duplicated, two renamed
 * tools rendered as raw JSON for five weeks with a green suite (#144). A name the
 * catalog has never heard of - an MCP tool, one a binding renamed - falls back to
 * a humanized label there, which is the same answer web chat gives.
 *
 * The result opens rather than showing, and only when the server sent one: a
 * page whose operator left `show_tool_results` off never receives it, so there is
 * nothing here to hide.
 */
function ToolLine({ step }: { step: Step }) {
  const t = useTranslations("chat.tools");
  const line = toolStep(step.name, step.args, step.result !== undefined, t);
  return (
    <div className="text-muted-foreground mb-1.5 text-xs">
      {step.result === undefined ? (
        <span>{line.label}</span>
      ) : (
        <details>
          <summary className="cursor-pointer">{line.label}</summary>
          <pre className="mt-1 max-h-40 overflow-auto text-[11px] whitespace-pre-wrap">
            {step.result}
          </pre>
        </details>
      )}
    </div>
  );
}
