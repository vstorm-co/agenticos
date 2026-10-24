"use client";

import type { CSSProperties } from "react";
import { useCallback, useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { MessageSquarePlus, Mic, MicOff, Paperclip, Send, User, X } from "lucide-react";
import { useTranslations } from "next-intl";

import { DictationBar } from "@/components/chat/dictation-bar";
import { dictationHint, DictationStrip, movesOn } from "@/components/chat/dictation-strip";
import { MarkdownContent } from "@/components/chat/markdown-content";
import { useFollowContent } from "@/hooks/use-follow-content";
import { TurnParts } from "@/components/chat/turn-parts";
import { usePublicConfig } from "@/components/public-config/public-config-provider";
import { Button, Input } from "@/components/ui";
import { useMicrophone, VoiceGlow } from "@/components/ui/voice-glow";
import { VoiceCallButton } from "@/components/voice/voice-call-button";
import { voiceFailureHint } from "@/components/voice/voice-call-strip";
import {
  callActive,
  showVoiceApproval,
  VoiceCallBar,
  VoiceCallFeed,
} from "@/components/voice/voice-call-view";
import { useChanged } from "@/hooks/use-changed";
import { useDictation } from "@/hooks/use-dictation";
import { useFocusAfterCall } from "@/hooks/use-focus-after-call";
import { useVoiceSession } from "@/hooks/use-voice-session";
import { dictateOnPage, type DictationSend } from "@/lib/dictation-api";
import { MediaSurfaceContext, type MediaSurface } from "@/lib/generated-media";
import { cn } from "@/lib/utils";
import type { MessagePart } from "@/types";
import type { HostedPageConfig } from "@/types/hosted";
import type { VoiceReadiness, VoiceSavedTurn, VoiceTransport } from "@/types/voice";

/**
 * The browser's voice processing for a recording that is transcribed, as the
 * console's composer asks for it: what a speech model wants to hear.
 */
const DICTATION_CONSTRAINTS = {
  constraints: { echoCancellation: true, noiseSuppression: true, autoGainControl: true },
};

/**
 * One turn of the thread, in the shape web chat renders.
 *
 * `MessagePart[]` rather than a text field and a list of steps beside it, and that
 * is not a detail: parts carry the *order*, so an agent that says a sentence, calls
 * a tool and then says another arrives as three things in that sequence. The page's
 * own shape could not express it - the text was one accumulating string and the
 * steps a separate list, so a turn like that rendered its whole answer above all of
 * its work whatever actually happened.
 */
interface Turn {
  role: "user" | "assistant";
  parts: MessagePart[];
  /**
   * When the turn was written, as an ISO string.
   *
   * Off the `history` frame for a replayed thread and stamped here for a live one,
   * so a bookmarked link comes back with the times still under its turns - which is
   * the visit continuity exists for.
   */
  at?: string;
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
      return ((payload.messages as { role: Turn["role"]; text: string; at?: string }[]) ?? []).map(
        (message, index) => ({
          role: message.role,
          at: message.at,
          parts: [{ id: `h${index}`, type: "text", content: message.text }],
        }),
      );
    case "text_delta":
      return intoLive(said, (parts) => extend(parts, "text", String(payload.content)));
    case "thinking_delta":
      return intoLive(said, (parts) => extend(parts, "thinking", String(payload.content)));
    case "tool_call":
      return intoLive(said, (parts) => [
        ...parts,
        {
          id: `tool-${String(payload.tool_call_id)}`,
          type: "tool",
          toolCall: {
            id: String(payload.tool_call_id),
            name: String(payload.tool_name),
            // Absent where the operator does not show what a step returned, and an
            // empty object is the honest stand-in: `toolStep` reads the arguments to
            // name a step by its subject, and finds none rather than being handed a
            // subject that was never sent.
            args: (payload.args as Record<string, unknown> | undefined) ?? {},
            status: "running",
          },
        },
      ]);
    case "tool_result":
      return intoLive(said, (parts) =>
        parts.map((part) => {
          const call = part.toolCall;
          if (call === undefined || call.id !== payload.tool_call_id) return part;
          return {
            ...part,
            toolCall: { ...call, result: String(payload.content), status: "completed" as const },
          };
        }),
      );
    case "final_result":
      // What the run ended with. It *replaces* the streamed text rather than
      // appending to it - they are the same words - and a provider that streamed no
      // deltas leaves this as the only copy of them. Empty on a turn that parked,
      // which `error` then explains.
      return payload.output === ""
        ? [...said]
        : intoLive(said, (parts) => settle(parts, String(payload.output)));
    case "complete":
      return said.map((turn) => (turn.live === true ? { ...turn, ...finished(turn) } : turn));
    case "error":
      // A turn that produced nothing leaves an empty bubble behind, so the
      // refusal replaces it rather than appearing under it. A turn that produced
      // something is finished the way `complete` finishes it - the route's own
      // failure path fails a turn with no trailing `complete`, and a running
      // spinner must not keep animating under the refusal.
      return [
        ...withoutEmptyLive(said).map((turn) =>
          turn.live === true ? { ...turn, ...finished(turn) } : turn,
        ),
        refusal(String(payload.message)),
      ];
    default:
      return [...said];
  }
}

/** A refusal, as a turn of its own. */
function refusal(message: string): Turn {
  return { role: "assistant", at: now(), parts: [{ id: "err", type: "text", content: message }] };
}

/**
 * A spoken turn the call saved, as a turn of the thread - or nothing, for one
 * saved with no words (an answer that only ran a tool).
 *
 * Drawn from the frame rather than read back over the page's socket: a reread
 * is a reconnect, every reconnect counts against the address's admissions,
 * and a lively call saves a turn every few seconds.
 */
function spokenTurn(message: VoiceSavedTurn): Turn | null {
  if (message.content === "") return null;
  return {
    role: message.role === "user" ? "user" : "assistant",
    at: now(),
    parts: [{ id: `voice-${message.id}`, type: "text", content: message.content }],
  };
}

/**
 * The call button's readiness, from what the page's config already decided.
 *
 * `voice_conversation` arrives true only while a call would start, so there is
 * nothing to cross out and no reason to give: the button is either offered or
 * absent, as server dictation's microphone is.
 */
function offered(transport: VoiceTransport): VoiceReadiness {
  return {
    available: true,
    unavailable: null,
    transport,
    provider: null,
    model: null,
    cap_seconds: 0,
  };
}

/** Now, as the turn records it. Its own function so a test can hold it still. */
function now(): string {
  return new Date().toISOString();
}

/** Append to the trailing part of this kind, or open one. */
function extend(parts: MessagePart[], type: "text" | "thinking", content: string): MessagePart[] {
  const last = parts.at(-1);
  if (last !== undefined && last.type === type) {
    return [...parts.slice(0, -1), { ...last, content: (last.content ?? "") + content }];
  }
  return [...parts, { id: `${type}-${parts.length}`, type, content }];
}

/**
 * The answer as the run ended with it, on the part that was streaming it.
 *
 * On the trailing text part where there is one, so a turn that streamed and then
 * settled keeps one bubble rather than gaining a second identical one - and as a new
 * part where the words arrived only here, which is a provider that does not stream.
 */
function settle(parts: MessagePart[], output: string): MessagePart[] {
  const last = parts.at(-1);
  if (last !== undefined && last.type === "text") {
    return [...parts.slice(0, -1), { ...last, content: output }];
  }
  return [...parts, { id: `text-${parts.length}`, type: "text", content: output }];
}

/**
 * The turn is over, so nothing in it is still in flight.
 *
 * A call with no result when `complete` arrives never got one: the run broke, or
 * parked on it. `unfinished` is what web chat calls that, and it matters because it
 * is the one state that must not animate - a spinner under a turn that has ended is
 * a promise nothing is going to keep.
 */
function finished(turn: Turn): Pick<Turn, "live" | "parts"> {
  return {
    live: false,
    parts: turn.parts.map((part) => {
      const call = part.toolCall;
      if (call === undefined || call.status !== "running") return part;
      return { ...part, toolCall: { ...call, status: "unfinished" as const } };
    }),
  };
}

function intoLive(said: readonly Turn[], mutate: (parts: MessagePart[]) => MessagePart[]): Turn[] {
  const last = said.at(-1);
  if (last !== undefined && last.role === "assistant" && last.live === true) {
    return [...said.slice(0, -1), { ...last, parts: mutate(last.parts) }];
  }
  return [...said, { role: "assistant", parts: mutate([]), live: true, at: now() }];
}

function withoutEmptyLive(said: readonly Turn[]): Turn[] {
  const last = said.at(-1);
  const empty = last !== undefined && last.live === true && !said.at(-1)?.parts.some(hasContent);
  return empty ? said.slice(0, -1) : [...said];
}

function hasContent(part: MessagePart): boolean {
  return part.toolCall !== undefined || (part.content ?? "") !== "";
}

/** The key minted on this page load, per public key: where storage cannot keep it. */
const pageVisitorKeys = new Map<string, string>();

/**
 * Where a returning visitor's identity is kept, per public key.
 *
 * Per key rather than one for the whole browser: two hosted pages are two
 * conversations with two different agents, and a shared id would put them in the
 * same thread on the server.
 */
function visitorKeyFor(publicKey: string): string {
  try {
    const existing = window.localStorage.getItem(storageKeyFor(publicKey));
    if (existing) return existing;
  } catch {
    // "Block all cookies" makes even reading window.localStorage throw. A
    // visitor with that setting gets a fresh thread each visit rather than the
    // page failing to open at all.
  }
  // One key for the whole visit, so the page's socket, a call and an upload are
  // one visitor in one thread - also where storage reads but cannot keep what
  // was minted, being full.
  const held = pageVisitorKeys.get(publicKey);
  if (held === undefined) return mintVisitorKey(publicKey);
  keep(publicKey, held);
  return held;
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
  pageVisitorKeys.set(publicKey, minted);
  keep(publicKey, minted);
  return minted;
}

/** Store the visit's key where the next visit finds it, where storage allows. */
function keep(publicKey: string, key: string): void {
  try {
    window.localStorage.setItem(storageKeyFor(publicKey), key);
  } catch {
    // Blocked or full: the key lives only for this page load, so a bookmarked
    // link starts a new thread rather than resuming - the small failure to take.
  }
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
  const tDictation = useTranslations("hosted.dictation");
  const tVoice = useTranslations("hosted.voice");
  const { apiUrl, wsUrl } = usePublicConfig();
  // Same origin, not the address the API gave. `img-src 'self' blob: data: https:`
  // excludes an API on plain `http`, which is every development checkout and any
  // deployment that terminates TLS elsewhere - so the header and every turn's
  // gutter rendered a broken-image glyph with nothing saying why. `logo_url` stays
  // the answer to *whether* there is one: the reasons there might not be - `none`
  // chosen, `custom` with nothing uploaded, an avatar whose file has gone - are the
  // backend's to know, and it already decided them.
  const logoSrc =
    config.logo_url === null ? null : `/api/embed/${encodeURIComponent(config.public_key)}/logo`;
  const mediaSurface = useMemo<MediaSurface>(
    () => ({ kind: "hosted", publicKey: config.public_key }),
    [config.public_key],
  );
  const [turns, setTurns] = useState<Turn[]>([]);
  const [draft, setDraft] = useState("");
  const [thinking, setThinking] = useState(false);
  const [closed, setClosed] = useState<"refused" | "too-many" | "lost" | null>(null);
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
  const threadContentRef = useRef<HTMLDivElement | null>(null);
  const recognitionRef = useRef<SpeechRecognition | null>(null);
  const filePicker = useRef<HTMLInputElement | null>(null);
  const draftRef = useRef<HTMLInputElement | null>(null);
  // Whether the server's side of the page's socket is in the visitor's thread:
  // it replayed one, or the visitor wrote in it. Until then a call that creates
  // the thread has the socket reopened, so the next typed turn lands there too.
  const threadKnownRef = useRef(false);
  // Which thread is this page's - bumped by "New chat" - and which one the
  // call was started in, so a call left behind cannot write into the next.
  const pageThreadRef = useRef(0);
  const callThreadRef = useRef(0);

  // Server dictation: the console composer's recorder, bar, strip and glow,
  // pointed at this page's own route. `server` arrives only while a provider
  // and credential resolve - the backend sends `off` otherwise - so there is no
  // crossed-out microphone here and no account of the operator's setup.
  const server = config.dictation === "server";
  const mic = useMicrophone(DICTATION_CONSTRAINTS);
  const sendRecording = useMemo<DictationSend | null>(
    () =>
      server
        ? (recording, seconds, signal, onProgress) =>
            dictateOnPage(
              {
                apiUrl,
                publicKey: config.public_key,
                visitorKey: visitorKeyFor(config.public_key),
              },
              recording,
              seconds,
              signal,
              onProgress,
            )
        : null,
    [server, apiUrl, config.public_key],
  );
  const { state: dictation, actions: dictationActions } = useDictation({
    mic,
    send: sendRecording,
    maxSeconds: config.dictation_max_seconds,
    format: config.dictation_format,
  });
  const dictating =
    dictation.phase === "requesting" ||
    dictation.phase === "recording" ||
    dictation.phase === "transcribing";
  // Into the draft once per transcript, during render so the text never shows a
  // frame late; never sent - the visitor reads and edits it first.
  const transcript = dictation.transcript;
  if (useChanged(transcript?.id ?? null) && transcript !== null) {
    const join = draft !== "" && !/\s$/.test(draft) ? " " : "";
    setDraft(draft + join + transcript.text);
  }
  // Escape discards a recording wherever focus is: the composer is the only
  // thing on this page, and the bar that replaces the box holds the focus.
  const cancelDictation = dictationActions.cancel;
  useEffect(() => {
    if (!dictating) return;
    const onKey = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      event.preventDefault();
      cancelDictation();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [dictating, cancelDictation]);
  const transcriptId = transcript?.id ?? null;
  useEffect(() => {
    if (transcriptId !== null) draftRef.current?.focus();
  }, [transcriptId]);
  const dictationStrip = server
    ? dictationHint(
        {
          state: dictation,
          actions: dictationActions,
          maxSeconds: config.dictation_max_seconds,
          voiceSettingsHref: null,
          agentVoiceHref: null,
          visitor: true,
        },
        tDictation,
      )
    : null;

  useEffect(() => {
    const visitor = visitorKeyFor(config.public_key);
    const url = `${wsUrl}/api/v1/embed/${encodeURIComponent(config.public_key)}/ws?visitor=${visitor}`;
    const socket = new WebSocket(url);
    socketRef.current = socket;
    // Set before the cleanup closes the socket, so a teardown - an unmount, a
    // reconnect, "start a new chat" bumping `session` - does not read as the
    // server having dropped us and flash "connection lost" on the way out.
    let intentional = false;

    socket.onmessage = (event) => {
      const frame = JSON.parse(event.data as string);
      if (frame.type === "model_request_start") setThinking(true);
      if (frame.type === "complete" || frame.type === "error") setThinking(false);
      if (frame.type === "history") threadKnownRef.current = true;
      setTurns((said) => fold(said, frame.type as string, frame.data ?? {}));
    };
    socket.onclose = (event) => {
      if (intentional) return;
      setThinking(false);
      if (event.code === 4029) setClosed("too-many");
      else if (event.code === 4003) setClosed("refused");
      // Any other close - a network blip, uvicorn restarting mid-deploy, the 1006
      // an abnormal drop carries, the 1011 a reader too slow to keep up gets - is
      // not a refusal and not a limit. The composer is disabled rather than left to
      // swallow a `send` silently, and the visitor is offered a reconnect that keeps
      // their thread.
      else setClosed("lost");
      // A dropped socket ends the turn as surely as an `error` frame does, and
      // nothing else will say so: without this the caret keeps pulsing and a tool
      // step stays running, under a notice saying the connection is gone.
      setTurns((said) =>
        said.map((turn) => (turn.live === true ? { ...turn, ...finished(turn) } : turn)),
      );
      // A dropped socket ends the turn as surely as an `error` frame does, and
      // nothing else will say so: without this the caret keeps pulsing and a tool
      // step stays running, under a notice saying the connection is gone.
    };

    return () => {
      intentional = true;
      socket.close();
    };
  }, [wsUrl, config.public_key, session]);

  useEffect(() => {
    const thread = threadRef.current;
    if (thread !== null) thread.scrollTop = thread.scrollHeight;
  }, [turns, thinking]);
  // And on growth the turns do not announce: an answer's last words are revealed
  // over frames after its turn has stopped changing.
  useFollowContent(threadRef, threadContentRef);

  // Reopen the socket on the *same* visitor key, so a dropped connection is
  // resumed rather than replaced: bumping `session` re-runs the effect and
  // `visitorKeyFor` reads the stored key, keeping the thread. Unlike startFresh,
  // which mints a new key and so a new thread.
  const reconnect = useCallback(() => {
    setThinking(false);
    setClosed(null);
    setSession((count) => count + 1);
  }, []);

  // A voice call (#54), in the console's own call bar and call feed. Offered
  // only when the config says a call would start, so - as with server
  // dictation - there is no crossed-out button here and no account of the
  // operator's setup. Each saved turn joins the thread from its `turn_saved`
  // frame, and `spokenSaved` keeps its live caption from being drawn beside
  // it - unless the visitor has since started a new chat, which the call's
  // late turns do not belong to.
  const [spokenSaved, setSpokenSaved] = useState<ReadonlySet<string>>(() => new Set());
  const onTurnSaved = useCallback((message: VoiceSavedTurn) => {
    if (callThreadRef.current !== pageThreadRef.current) return;
    const turnId = message.turn_id;
    if (turnId !== null) setSpokenSaved((held) => new Set(held).add(turnId));
    const turn = spokenTurn(message);
    if (turn !== null) setTurns((said) => [...said, turn]);
  }, []);
  // When a call names its thread, the page's socket is reopened on the same
  // key - but only while that socket knows no thread. Its server side learned
  // the visitor's thread when it connected, so a first call creates one the
  // socket would not otherwise answer in; a socket already in the thread is
  // left alone, since reopening it replays the history over the thread on
  // screen, flattening its steps and dropping the page's own notices.
  const onConversation = useCallback(() => {
    if (callThreadRef.current !== pageThreadRef.current || threadKnownRef.current) return;
    threadKnownRef.current = true;
    reconnect();
  }, [reconnect]);
  const voice = useVoiceSession({ onTurnSaved, onConversation });
  const { start: startVoice, end: endCall, dismiss: dismissCall } = voice;
  const onCall = callActive(voice);
  const callTransport = config.voice_conversation ? config.voice_transport : null;
  // As in /chat: no call while an answer is still being written.
  const answering = thinking || turns.at(-1)?.live === true;
  const cancelServerDictation = dictationActions.cancel;
  const dictationIdle = dictation.phase === "idle";
  const startCall = useCallback(
    (transport: VoiceTransport) => {
      // One microphone at a time: a call and a dictation never run together.
      if (!dictationIdle) cancelServerDictation();
      void startVoice({
        kind: "embed",
        publicKey: config.public_key,
        visitorKey: visitorKeyFor(config.public_key),
        token: null,
        transport,
        // Briefed with what the page's address says, as a typed message is.
        context: suppliedFromUrl(config.variables),
      });
    },
    [dictationIdle, cancelServerDictation, startVoice, config.public_key, config.variables],
  );
  // Why a call did not start, in the visitor's words (`hosted.voice` holds the
  // keys `chat.voice` does): nobody here to ask, and no setup to point at.
  const voiceHint =
    callTransport === null
      ? null
      : voiceFailureHint(
          { call: voice.call, onRetry: () => startCall(callTransport), onDismiss: dismissCall },
          tVoice,
        );
  const composerStrip = voiceHint ?? dictationStrip;
  // Nor the browser's recogniser, which the call button sits beside. And the
  // call belongs to the thread it started in, whatever the page opens next.
  useEffect(() => {
    if (!onCall) return;
    recognitionRef.current?.stop();
    callThreadRef.current = pageThreadRef.current;
  }, [onCall]);
  // The bar took focus when the call started, and goes with it when it ends:
  // back to the box, unless the visitor has since put focus somewhere else.
  useFocusAfterCall(onCall, (lost) => {
    if (lost) draftRef.current?.focus();
  });

  const startFresh = useCallback(() => {
    // A call belongs to its thread: a new thread hangs it up.
    endCall();
    dismissCall();
    pageThreadRef.current += 1;
    threadKnownRef.current = false;
    mintVisitorKey(config.public_key);
    setTurns([]);
    setThinking(false);
    setClosed(null);
    setSession((count) => count + 1);
  }, [config.public_key, endCall, dismissCall]);

  /**
   * Dictate into the box using the browser's own recogniser - `browser` mode.
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
   * no session to proxy, and the upload is authorised by the public key in the path
   * and the visitor's own continuity key. That key rides an X-Visitor-Key header
   * rather than the query string: it is a bearer credential for the whole
   * transcript, and a query string lands in access logs. A refusal - too large, a
   * type nothing can read, a page whose operator turned this off - is said in the
   * thread rather than thrown away, because a picker that appears to do nothing is
   * worse than a sentence.
   */
  const attach = useCallback(
    async (file: File) => {
      setUploading(true);
      try {
        const body = new FormData();
        body.append("file", file);
        const visitor = visitorKeyFor(config.public_key);
        const response = await fetch(
          `${apiUrl}/api/v1/embed/${encodeURIComponent(config.public_key)}/files`,
          { method: "POST", body, headers: { "X-Visitor-Key": visitor } },
        );
        if (!response.ok) throw new Error("refused");
        const stored = (await response.json()) as { id: string; filename: string };
        setAttached((held) => [...held, stored]);
      } catch {
        setTurns((said) => [...said, refusal(t("uploadFailed"))]);
      } finally {
        setUploading(false);
      }
    },
    [apiUrl, config.public_key, t],
  );

  const send = useCallback(() => {
    const text = draft.trim();
    const socket = socketRef.current;
    if ((!text && attached.length === 0) || socket === null || socket.readyState !== WebSocket.OPEN)
      return;
    setTurns((said) => [
      ...said,
      {
        role: "user",
        at: now(),
        parts: [{ id: `said-${said.length}`, type: "text", content: text }],
      },
    ]);
    setDraft("");
    setAttached([]);
    // Typing on after a call: its summary has said its piece.
    dismissCall();
    threadKnownRef.current = true;
    socket.send(
      JSON.stringify({
        type: "message",
        text,
        file_ids: attached.map((file) => file.id),
        context: suppliedFromUrl(config.variables),
      }),
    );
  }, [draft, attached, config.variables, dismissCall]);

  return (
    // The operator's accent, applied through a CSS variable rather than a
    // hardcoded class so the send button carries their brand colour. Validated as
    // a hex on both the client field and the server, so interpolating it here is
    // safe.
    <div
      className="mx-auto flex h-dvh max-w-3xl flex-col px-4"
      style={{ "--hosted-accent": config.accent } as CSSProperties}
    >
      <header className="flex items-center gap-3 border-b py-4">
        {logoSrc !== null && (
          // A plain `<img>`, not `next/image`: the route below is a proxy, and
          // `next/image` would want it in `next.config` remote patterns - which it
          // must not need to be for a self-hosted deployment to render its own logo.
          // eslint-disable-next-line @next/next/no-img-element
          <img src={logoSrc} alt="" className="h-8 w-8 rounded-md object-cover" />
        )}
        <h1 className="flex-1 text-lg font-semibold">{config.title}</h1>
        {config.allow_new_conversation && (
          <Button variant="ghost" size="sm" onClick={startFresh}>
            <MessageSquarePlus className="h-4 w-4" />
            {t("newConversation")}
          </Button>
        )}
      </header>

      <div ref={threadRef} className="flex-1 scrollbar-thin overflow-y-auto py-4">
        <div ref={threadContentRef} className="space-y-3">
          {/* Markdown, like the answer and for the same reason: the operator writes it
              in a Markdown editor, so printing the asterisks would be the one place on
              this page that shows the source instead of the text. Never sent to the
              model - a greeting in the model's history is a turn the agent thinks it
              took. */}
          {config.welcome !== "" && turns.length === 0 && (
            <div className="text-muted-foreground prose-sm max-w-none text-sm">
              <MarkdownContent content={config.welcome} />
            </div>
          )}
          {/* A generated image or clip is read through this page's key with the link
              the socket handed out - the console's address needs a session (#2309). */}
          <MediaSurfaceContext.Provider value={mediaSurface}>
            {turns.map((turn, index) => (
              <HostedTurn key={index} turn={turn} logoSrc={logoSrc} agentName={config.agent_name} />
            ))}
          </MediaSurfaceContext.Provider>
          {/* The call as it happens: live captions in the turns being spoken, the
              agent's work, and the summary when it ends. No approval controls -
              a visitor cannot approve, and the server leaves tools that need one
              out of their calls. */}
          {callTransport !== null && (
            <VoiceCallFeed
              session={voice}
              agentName={config.agent_name}
              canDecide={false}
              hidden={spokenSaved}
              onCallAgain={() => startCall(callTransport)}
              onContinueInText={endCall}
              // The faces and words the page's own turns use: a caption must
              // not change face when its saved turn replaces it, and a visitor
              // has no budget or access for the call's end to name.
              callerAvatar={<User className="h-4 w-4" />}
              agentAvatar={<AgentFace logoSrc={logoSrc} agentName={config.agent_name} />}
              endingCopy={tVoice}
            />
          )}
          {thinking && <p className="text-muted-foreground text-sm">{t("thinking")}</p>}
          {closed !== null && (
            <div className="text-muted-foreground flex items-center gap-2 text-sm">
              <span>
                {closed === "too-many"
                  ? t("tooManyConnections")
                  : closed === "lost"
                    ? t("connectionLost")
                    : t("unavailable")}
              </span>
              {closed === "lost" && (
                <Button variant="ghost" size="sm" onClick={reconnect}>
                  {t("reconnect")}
                </Button>
              )}
            </div>
          )}
        </div>
      </div>

      {uploading && (
        <p className="text-muted-foreground pt-2 text-xs" role="status">
          {t("uploading")}
        </p>
      )}
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

      {/* The composer as one card, which is the shape web chat's is: a border that
          follows focus, the field and its controls inside it, and nothing between them
          and the edge. It used to be a bordered input with three buttons beside it on
          a hairline - the same controls, arranged like a form rather than like a
          composer. What is *not* in the card is the usage strip that sits at the top
          of the dashboard's: what a turn cost is the operator's business. The glow
          and the strip under the card are server dictation's, lit only while a
          recording is open or on its way. */}
      {onCall && (
        <div className="@container mb-4">
          <VoiceCallBar
            session={voice}
            agentName={config.agent_name}
            canDecide={false}
            onShowApproval={showVoiceApproval}
            endingCopy={tVoice}
          />
        </div>
      )}
      {/* Kept mounted while a call is on, so a draft and its attachments are
          still there when it ends. */}
      <div hidden={onCall}>
        <VoiceGlow
          className="mb-4"
          stream={mic.stream}
          active={dictation.phase === "recording" || dictation.phase === "transcribing"}
          processing={dictation.phase === "transcribing" && dictation.upload === null}
        >
          <form
            className={cn(
              "bg-card border-border focus-within:border-foreground/30 rounded-2xl border transition-colors",
              composerStrip !== null && "rounded-b-none",
            )}
            onSubmit={(event) => {
              event.preventDefault();
              send();
            }}
          >
            {dictating ? (
              <div className="px-3 py-1 sm:px-4">
                <DictationBar state={dictation} actions={dictationActions} />
              </div>
            ) : (
              <div className="flex items-end gap-2 px-3 py-2 sm:px-4">
                <Input
                  ref={draftRef}
                  value={draft}
                  onChange={(event) => setDraft(event.target.value)}
                  onKeyDown={(event) => {
                    if (dictation.inserted && movesOn(event.key))
                      dictationActions.dismissInserted();
                  }}
                  placeholder={t("placeholder")}
                  aria-label={t("placeholder")}
                  disabled={closed !== null}
                  className="min-h-[40px] flex-1 border-0 bg-transparent shadow-none focus-visible:ring-0"
                />
                <div className="flex shrink-0 items-center gap-0.5 pb-1">
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
                        className="h-9 w-9"
                        disabled={closed !== null || uploading}
                        onClick={() => filePicker.current?.click()}
                        aria-label={t("attach")}
                      >
                        <Paperclip className="text-muted-foreground h-4 w-4" />
                      </Button>
                    </>
                  )}
                  {callTransport !== null && (
                    <VoiceCallButton
                      readiness={offered(callTransport)}
                      failed={false}
                      disabled={closed !== null || answering}
                      onStart={() => startCall(callTransport)}
                      setUpHref={null}
                    />
                  )}
                  {server && (
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      className="h-9 w-9"
                      onClick={() => void dictationActions.start()}
                      disabled={closed !== null}
                      aria-label={t("startDictation")}
                    >
                      <Mic className="text-muted-foreground h-4 w-4" />
                    </Button>
                  )}
                  {config.dictation === "browser" && canDictate && (
                    <Button
                      type="button"
                      variant="ghost"
                      size="icon"
                      className="h-9 w-9"
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
                    size="icon"
                    className="h-9 w-9 rounded-full text-white hover:opacity-90"
                    style={{ backgroundColor: "var(--hosted-accent)" }}
                    disabled={closed !== null || (draft.trim() === "" && attached.length === 0)}
                  >
                    <Send className="h-4 w-4" />
                    <span className="sr-only">{t("send")}</span>
                  </Button>
                </div>
              </div>
            )}
          </form>
          <DictationStrip hint={composerStrip} />
        </VoiceGlow>
      </div>
    </div>
  );
}

/** The agent's face on this page: the operator's logo, or the agent's initial. */
function AgentFace({ logoSrc, agentName }: { logoSrc: string | null; agentName: string }) {
  return logoSrc !== null ? (
    // The page's own picture, which is the closest thing this surface has to an
    // agent avatar - the authenticated avatar route is not reachable from here,
    // and the logo is the one image a hosted page may already hand out.
    // eslint-disable-next-line @next/next/no-img-element
    <img src={logoSrc} alt="" className="h-full w-full object-cover" />
  ) : (
    // The initial, which is what `AgentAvatar` falls back to in the dashboard.
    // A generic robot glyph is the one thing on this page that looked like a
    // different product.
    <span className="text-foreground text-sm font-medium">
      {(agentName.trim()[0] ?? "?").toUpperCase()}
    </span>
  );
}

/**
 * One turn, laid out the way web chat lays one out.
 *
 * An avatar in the gutter, the person's words in a bubble on the right, the agent's
 * as prose on the left, and its work on a rail between them - and every one of those
 * comes from `TurnParts`, so the two surfaces cannot drift into rendering the same
 * turn two ways. What is deliberately absent is everything about being a member: no
 * agent name and version, no cost, no rating, no regenerate, no sources panel. See
 * `docs/channels.md` for why each of those is member-only.
 */
function HostedTurn({
  turn,
  logoSrc,
  agentName,
}: {
  turn: Turn;
  logoSrc: string | null;
  agentName: string;
}) {
  const isUser = turn.role === "user";
  return (
    <div
      className={cn(
        "group relative flex gap-2 py-3 sm:gap-4 sm:py-4",
        isUser && "flex-row-reverse",
      )}
    >
      <div
        className={cn(
          "z-10 flex h-8 w-8 flex-shrink-0 items-center justify-center overflow-hidden rounded-full text-sm font-medium sm:h-9 sm:w-9",
          isUser ? "bg-foreground text-background" : "bg-muted text-foreground",
        )}
      >
        {isUser ? (
          <User className="h-4 w-4" />
        ) : (
          <AgentFace logoSrc={logoSrc} agentName={agentName} />
        )}
      </div>
      <div
        className={cn(
          "max-w-[88%] flex-1 space-y-2 overflow-hidden sm:max-w-[85%]",
          isUser && "flex flex-col items-end",
        )}
      >
        {/* Which agent answered, above the turn it answered - the same line web chat
            draws. Without it an answer has no author on a page whose whole subject is
            one agent. The *version* is not here: what a stored spec is called is an
            internal fact, and a visitor has nothing to do with it. */}
        {!isUser && (
          <p className="text-muted-foreground font-mono text-xs tracking-wider uppercase">
            {agentName}
          </p>
        )}
        <TurnParts
          parts={turn.parts}
          isStreaming={turn.live === true}
          isUser={isUser}
          // None to offer: reading the organization's MCP connections needs a session,
          // so a call that came from one reads as a humanized name here.
          mcpServers={[]}
        />
        {/* The time, on the side the turn is on. What is deliberately not beside it is
            the turn's cost, which web chat prints here and which is the operator's
            business rather than the visitor's - see `docs/channels.md`. */}
        {turn.at !== undefined && turn.live !== true && (
          <span className={cn("text-muted-foreground block text-xs", isUser && "text-right")}>
            {new Date(turn.at).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}
          </span>
        )}
      </div>
    </div>
  );
}
