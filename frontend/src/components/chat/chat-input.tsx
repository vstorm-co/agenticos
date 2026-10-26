"use client";

import { useState, useRef, useEffect, useLayoutEffect, useCallback, useMemo } from "react";
import type { ReactNode } from "react";
import { getErrorMessage } from "@/lib/api-error";
import { Button, Spinner } from "@/components/ui";
import { Send, Mic, MicOff } from "lucide-react";
import { toast } from "sonner";

import { uploadFile, type FileUploadResponse } from "@/lib/file-api";
import { usePublicConfig } from "@/components/public-config/public-config-provider";
import { createPortal } from "react-dom";

import { AttachmentCard, PendingAttachmentCard } from "./attachment-card";
import { AttachmentRow } from "./attachment-row";
import { ReplyingTo } from "./reply-quote";
import { useChatStore } from "@/stores";
import { ComposerSheet } from "./composer-sheet";

/**
 * Render `row` where the page wants it, or in place when it named nowhere.
 *
 * The attachments belong *above* the composer, and the box around the composer is
 * drawn by the page rather than by this component - so the row cannot simply be
 * the first child here. A portal keeps the state where the uploads happen and
 * puts the markup where it reads correctly; lifting `attachedFiles`, `pending`
 * and every upload path into the page would be a much larger change for a
 * question about layout. Without a slot it renders here, which is what any other
 * mounting of this composer gets.
 */
function into(slot: HTMLElement | null | undefined, row: React.ReactNode): React.ReactNode {
  return slot == null ? row : createPortal(row, slot);
}
import {
  BUILTIN_COMMANDS,
  resolveBuiltin,
  searchCommands,
  type SlashCommand,
  type SlashCommandContext,
} from "./slash-commands";
import { SlashCommandPalette } from "./slash-command-palette";
import { ComposerEditor, type ComposerEditorHandle } from "./composer-editor";
import { ComposerHints } from "./composer-hints";
import { MentionPalette } from "./mention-palette";
import { useMentionables } from "@/hooks/use-mentionables";
import {
  insertMention,
  matching,
  mentionAt,
  stillMentioned,
  type MentionQuery,
} from "@/lib/mentions";
import type { Mentionable } from "@/types/mention";
import { FileDropOverlay } from "@/components/files";
import { useChanged } from "@/hooks/use-changed";
import { useFileDrop } from "@/hooks/use-file-drop";
import { useTranslations } from "next-intl";
import type { UseMicrophoneResult } from "voice-glow";
import { wordCount, type DictationActions, type DictationState } from "@/hooks/use-dictation";
import type { ComposerDictation as DictationEngine } from "@/lib/dictation-api";

import { movesOn } from "./dictation-strip";

/**
 * Dictation for the selected agent, as the composer needs it.
 *
 * The recording itself lives in the page (`useDictation` beside the microphone),
 * because the glow around the box reads its phase; this component only shows
 * it, and inserts what comes back.
 */
export interface ComposerDictation {
  /**
   * `server` when the selected agent's Dictation switch sends recordings to a
   * provider it can reach; `browser`, the browser's own recognition, otherwise.
   */
  engine: DictationEngine;
  state: DictationState;
  actions: DictationActions;
}

/**
 * Past this many characters, a paste is a file rather than a message.
 *
 * The whole design decision is this number. Somebody who pastes a paragraph and
 * presses enter meant that to *be* the message, so the threshold has to sit
 * above anything a person would type-or-paste as a question — 2000 characters is
 * roughly 350 words, longer than any question and shorter than any document.
 * Below it nothing changes: the text lands in the textarea as it always has.
 */
const PASTE_AS_FILE_CHARS = 2000;

/** What one message may point at; the server refuses a frame with more (`agent_chat.MAX_MENTIONS`). */
const MAX_MENTIONS = 10;

/** A file queued for upload, shown as a card before the server has answered. */
interface PendingUpload {
  key: number;
  name: string;
  size: number;
}

/**
 * An attached file and whether it arrived as a paste.
 *
 * The flag travels with the file rather than in a second set keyed by id. It is
 * knowledge only this component has — the server is handed a `text/plain` file
 * and cannot tell one from any other — so a parallel structure would be a
 * parallel structure that can drift, for no gain.
 */
interface Attachment {
  file: FileUploadResponse;
  pasted: boolean;
}

interface ChatInputProps {
  onSend: (
    message: string,
    fileIds?: string[],
    files?: FileUploadResponse[],
    mentions?: Mentionable[],
  ) => void;
  /**
   * The agent this turn is addressed to, whose servers, delegates and knowledge
   * `@` offers (#2189). Absent where the composer offers no mentions.
   */
  agentId?: string | null;
  /** Offer what the Builder's draft reaches - its test panel runs the draft. */
  mentionsFromDraft?: boolean;
  /** Suggest what can be asked while the box is empty - a conversation with nothing in it yet. */
  hints?: boolean;
  disabled?: boolean;
  isProcessing?: boolean;
  /** A live or parked run can be stopped even while the composer is disabled. */
  canStop?: boolean;
  stopDisabled?: boolean;
  /** When set, a stop control replaces the send button for a stoppable run. */
  onStop?: () => void;
  /** Local actions for slash commands. Wire from <ChatContainer>. */
  slashContext?: SlashCommandContext;
  /** Effective slash commands (built-ins + user customs, after overrides). */
  commands?: SlashCommand[];
  /**
   * Where to draw what is attached, when the page wants it somewhere else.
   *
   * The row belongs above the composer's own box, which this component is inside
   * rather than around - see `into`. Absent, it renders in place.
   */
  attachmentSlot?: HTMLElement | null;
  /**
   * The microphone the voice glow listens to, opened by this component's own
   * button and owned by the caller - the glow is drawn around the composer box,
   * which this component is inside rather than around. Optional, because a
   * caller that draws no glow has nothing to listen with and dictation does not
   * need it: the Web Speech API captures its own audio.
   */
  mic?: UseMicrophoneResult;
  /**
   * Who answers - drawn on the control row after the attach button.
   *
   * Slots rather than a row of the caller's own, because the send button has to
   * stay inside this `<form>` to submit it.
   */
  controlsSlot?: ReactNode;
  /** Opens the project picker from the `+`; absent where a chat cannot change project. */
  onProject?: () => void;
  /**
   * Icons drawn before the microphone: what the conversation is using, and the
   * model it runs on. Icons, because a line of readings and a model's name took
   * the width of the row and were read past on every message.
   */
  actionsSlot?: ReactNode;
  /**
   * Drawn in Send's place while there is nothing to send - the call button, so
   * an empty box offers a call and a written one sends it (#2301).
   */
  idleSlot?: ReactNode;
  /**
   * The socket is down: the box says it is reconnecting where it would ask for a
   * message - the one place a person looks when they cannot send (#2301).
   */
  offline?: boolean;
  /**
   * The selected agent's dictation engine and, for `server`, the recording.
   * Absent, the microphone is the browser's own speech recognition.
   */
  dictation?: ComposerDictation;
  /**
   * Hears when the browser's own recognition starts listening, with how to stop
   * it, and when it stops - for the page's dictation pill (#54).
   */
  onListeningChange?: (stop: (() => void) | null) => void;
  /**
   * Files handed in from outside the composer - the AI Architect's screenshot of
   * the page (#2063) - attached as if picked, once per `id`.
   */
  incoming?: IncomingFiles | null;
  /** Called as the person types, so a shared chat can say they are. */
  onTyping?: () => void;
  /** Whether the box holds words of the person's own, as it changes. */
  onDraftChange?: (drafting: boolean) => void;
  /**
   * Projects `@` offers beside what the agent reaches, before the first message;
   * picking one starts the chat in it rather than mentioning it.
   */
  projects?: Mentionable[];
  onPickProject?: (projectId: string) => void;
}

/** Files to attach from outside the composer, once per `id`, and words to go with them. */
export interface IncomingFiles {
  id: number;
  files: File[];
  /** Written into the message, after whatever is already being typed. */
  text?: string;
}

/** Whether typing happens on a touch keyboard - a phone or a tablet. */
function touchKeyboard(): boolean {
  return typeof window !== "undefined" && window.matchMedia?.("(pointer: coarse)").matches === true;
}

export function ChatInput({
  onSend,
  disabled,
  isProcessing,
  canStop = isProcessing,
  stopDisabled = false,
  onStop,
  slashContext,
  commands,
  attachmentSlot,
  mic,
  controlsSlot,
  onProject,
  actionsSlot,
  idleSlot,
  offline = false,
  dictation,
  onListeningChange,
  incoming = null,
  agentId = null,
  mentionsFromDraft = false,
  hints = false,
  onTyping,
  onDraftChange,
  projects,
  onPickProject,
}: ChatInputProps) {
  const tErrors = useTranslations("errors");
  const t = useTranslations("chat.input");
  // The message this turn will answer, chosen with Reply on it.
  const replyTo = useChatStore((state) => state.replyTo);
  const setReplyTo = useChatStore((state) => state.setReplyTo);
  const tCommands = useTranslations("chat.commands");
  const tDictation = useTranslations("chat.dictation");
  const { chatMaxUploadSizeMb } = usePublicConfig();
  const [message, setMessage] = useState("");
  const drafting = message.trim().length > 0;
  useEffect(() => onDraftChange?.(drafting), [drafting, onDraftChange]);
  const [attachedFiles, setAttachedFiles] = useState<Attachment[]>([]);
  const [pending, setPending] = useState<PendingUpload[]>([]);
  const [isListening, setIsListening] = useState(false);
  const pendingKey = useRef(0);
  const isUploading = pending.length > 0;
  // Slash-command palette state. Open while message starts with "/" and the
  // caller wired a context - without one, commands have nothing to do.
  const [paletteIndex, setPaletteIndex] = useState(0);
  const editorRef = useRef<ComposerEditorHandle>(null);
  // Reply was just chosen on a message: the person goes on to type the answer.
  useEffect(() => {
    if (replyTo) editorRef.current?.focus();
  }, [replyTo]);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const recognitionRef = useRef<SpeechRecognition | null>(null);

  const server = dictation?.engine === "server" ? dictation : null;
  const phase = server?.state.phase ?? "idle";
  // The box is the recording's while it runs and while its text is on the way:
  // nothing typed then would survive the insertion, and nothing may be sent.
  const dictating = phase === "requesting" || phase === "recording" || phase === "transcribing";
  // Where the person was in the text when they pressed the mic, and the text it
  // points into; the transcript lands there, replacing a selection.
  const [caret, setCaret] = useState<{ from: number; to: number; text: string } | null>(null);
  const [placeCaret, setPlaceCaret] = useState<{ at: number } | null>(null);
  const [announcement, setAnnouncement] = useState("");

  if (useChanged(phase)) {
    if (phase === "recording") setAnnouncement(tDictation("announceRecording"));
    else if (phase === "transcribing") setAnnouncement(tDictation("announceTranscribing"));
  }
  const remaining = phase === "recording" ? (server?.state.remaining ?? null) : null;
  if (useChanged(remaining !== null) && remaining !== null) {
    setAnnouncement(tDictation("announceLeft", { count: remaining }));
  }
  // Once per transcript: inserted during render, so the text and the caret
  // never show a frame apart.
  const transcript = server?.state.transcript ?? null;
  if (useChanged(transcript?.id ?? null) && transcript !== null && caret !== null) {
    // The box is writable while a failed recording waits for Retry, so the text
    // can change between the press and the transcript. The saved offsets point
    // into text that is gone then, and the transcript goes at the end instead.
    const kept = message === caret.text;
    const from = kept ? caret.from : message.length;
    const to = kept ? caret.to : message.length;
    const before = message.slice(0, from);
    const after = message.slice(to);
    const join = before.length > 0 && !/\s$/.test(before) ? " " : "";
    const gap = after.length > 0 && !/^\s/.test(after) ? " " : "";
    const inserted = join + transcript.text + gap;
    setMessage(before + inserted + after);
    setCaret(null);
    setPlaceCaret({ at: from + inserted.length });
    setAnnouncement(tDictation("announceInserted", { count: wordCount(transcript.text) }));
  }

  // After the render that holds the text: focus the box and put the caret
  // after what was inserted, ready to edit it.
  useEffect(() => {
    if (placeCaret === null) return;
    const frame = requestAnimationFrame(() => editorRef.current?.setCaret(placeCaret.at));
    return () => cancelAnimationFrame(frame);
  }, [placeCaret]);

  // Focus went to <body> with the bar, which unmounts when dictation ends without
  // a transcript; back to the box, beside the strip that says what happened.
  const wasDictating = useRef(false);
  useEffect(() => {
    const ended = wasDictating.current && !dictating;
    wasDictating.current = dictating;
    if (ended && document.activeElement === document.body) editorRef.current?.focus();
  }, [dictating]);

  const startDictation = () => {
    const end = { from: message.length, to: message.length };
    setCaret({ ...(editorRef.current?.selection() ?? end), text: message });
    void server?.actions.start();
  };

  const showPalette = !!slashContext && message.startsWith("/") && !message.includes("\n");
  // `@`-mentions (#2189): what was picked, and the one being typed at the caret.
  // A pick stays in the text as `@Name`; deleting that text unpicks it, so what
  // is sent is always what the message still says.
  const [picked, setPicked] = useState<Mentionable[]>([]);
  const mentions = useMemo(() => stillMentioned(message, picked), [message, picked]);
  const [mentionQuery, setMentionQuery] = useState<MentionQuery | null>(null);
  const [mentionIndex, setMentionIndex] = useState(0);
  const mentionOpen = mentionQuery !== null && agentId !== null && !showPalette;
  const offered = useMentionables(agentId, mentionsFromDraft);
  const mentionMatches = useMemo(
    () =>
      mentionOpen && mentionQuery
        ? matching([...offered.items, ...(projects ?? [])], mentionQuery.query)
        : [],
    [mentionOpen, mentionQuery, offered.items, projects],
  );
  if (useChanged(`${mentionMatches.length}|${mentionQuery?.query ?? ""}`)) setMentionIndex(0);
  // Another agent's servers and knowledge are not this one's, so a switch drops
  // what was picked for the previous one rather than sending what it cannot reach.
  if (useChanged(agentId ?? "") && picked.length > 0) setPicked([]);

  // Where the caret goes once the picked `@query` is replaced - set as that text
  // commits, so the next keystroke lands after what was picked.
  const caretAfterPick = useRef<number | null>(null);
  useLayoutEffect(() => {
    if (caretAfterPick.current === null) return;
    editorRef.current?.setCaret(caretAfterPick.current);
    caretAfterPick.current = null;
  }, [message]);

  const typed = (text: string, at: number) => {
    setMessage(text);
    setMentionQuery(mentionAt(text, at));
    if (text.trim()) onTyping?.();
  };

  const full = mentions.length >= MAX_MENTIONS;
  const pickMention = (item: Mentionable) => {
    if (mentionQuery === null) return;
    if (item.kind === "project") {
      // Not a word in the message: the chat moves into the project, and the
      // `@` typed to find it goes.
      setMentionQuery(null);
      const rest = message.slice(mentionQuery.start + 1 + mentionQuery.query.length);
      setMessage(message.slice(0, mentionQuery.start) + rest.replace(/^ /, ""));
      caretAfterPick.current = mentionQuery.start;
      onPickProject?.(item.id);
      return;
    }
    if (full && !mentions.includes(item)) return;
    setMentionQuery(null);
    const next = insertMention(message, mentionQuery, item);
    setMessage(next.text);
    caretAfterPick.current = next.caret;
    setPicked(mentions.includes(item) ? mentions : [...mentions, item]);
  };
  // The palette before the user's own commands have loaded: the built-ins, with their
  // copy resolved here because the registry holds keys (#446).
  const allCommands = useMemo(
    () => commands ?? BUILTIN_COMMANDS.map((command) => resolveBuiltin(command, tCommands)),
    [commands, tCommands],
  );
  const filteredCommands = useMemo(
    () => (showPalette ? searchCommands(allCommands, message) : []),
    [showPalette, message, allCommands],
  );

  // Back to the first suggestion whenever the list underneath the cursor
  // changes, during render - an effect would highlight the old row for a frame.
  if (useChanged(`${filteredCommands.length}|${message}`)) setPaletteIndex(0);

  useEffect(() => {
    if (!isProcessing && !isUploading) editorRef.current?.focus();
  }, [isProcessing, isUploading]);

  const runSlashCommand = useCallback(
    (cmd: SlashCommand) => {
      if (cmd.action.kind === "client") {
        cmd.action.run(slashContext!);
        setMessage("");
        return;
      }
      // send-as-message - replace the slash with the canned prompt and send
      // through the normal flow so it lands as a regular user turn.
      const files = attachedFiles.length > 0 ? attachedFiles.map((a) => a.file) : undefined;
      onSend(
        cmd.action.replaceWith,
        files?.map((f) => f.id),
        files,
      );
      setMessage("");
      setAttachedFiles([]);
    },
    [attachedFiles, onSend, slashContext],
  );

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (dictating) return;
    if (showPalette && filteredCommands[paletteIndex]) {
      runSlashCommand(filteredCommands[paletteIndex]);
      return;
    }
    const trimmed = message.trim();
    if (!trimmed && attachedFiles.length === 0) return;
    if (disabled || isUploading) return;

    const files = attachedFiles.length > 0 ? attachedFiles.map((a) => a.file) : undefined;
    onSend(
      trimmed || t("analyzeFiles"),
      files?.map((f) => f.id),
      files,
      mentions.length > 0 ? mentions : undefined,
    );
    setMessage("");
    setAttachedFiles([]);
    setPicked([]);
    setMentionQuery(null);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
    // The note under the box saying the text landed goes with the next key.
    if (server?.state.inserted && movesOn(e.key)) server.actions.dismissInserted();
    if (dictating) {
      // Enter finishes the recording rather than sending; Escape is the form's.
      if (e.key === "Enter") {
        e.preventDefault();
        if (phase === "recording") server?.actions.stop();
      }
      return;
    }
    if (mentionOpen) {
      if (e.key === "Escape") {
        e.preventDefault();
        setMentionQuery(null);
        return;
      }
      if (mentionMatches.length > 0) {
        if (e.key === "ArrowDown") {
          e.preventDefault();
          setMentionIndex((i) => (i + 1) % mentionMatches.length);
          return;
        }
        if (e.key === "ArrowUp") {
          e.preventDefault();
          setMentionIndex((i) => (i - 1 + mentionMatches.length) % mentionMatches.length);
          return;
        }
        if (e.key === "Enter" || e.key === "Tab") {
          e.preventDefault();
          const item = mentionMatches[mentionIndex];
          if (item) pickMention(item);
          return;
        }
      }
    }
    if (showPalette && filteredCommands.length > 0) {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setPaletteIndex((i) => (i + 1) % filteredCommands.length);
        return;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setPaletteIndex((i) => (i - 1 + filteredCommands.length) % filteredCommands.length);
        return;
      }
      if (e.key === "Tab") {
        // Tab autocompletes to the highlighted command name.
        e.preventDefault();
        const cmd = filteredCommands[paletteIndex];
        if (cmd) setMessage("/" + cmd.name + " ");
        return;
      }
      if (e.key === "Escape") {
        e.preventDefault();
        setMessage("");
        return;
      }
    }
    // On a touch keyboard Enter is a new line, as in every messaging app: there
    // is no Shift to hold for one, and the send button is a thumb away (#2066).
    if (e.key === "Enter" && !e.shiftKey && !touchKeyboard()) {
      e.preventDefault();
      handleSubmit(e);
    }
  };

  // Through a ref: `useMicrophone` answers a new object every render, and a stop
  // that changed with it was handed to the page on every render while the browser
  // listened - which re-rendered this, which handed it over again, without end.
  const micRef = useRef(mic);
  useLayoutEffect(() => {
    micRef.current = mic;
  });
  const stopListening = useCallback(() => {
    recognitionRef.current?.stop();
    micRef.current?.stop();
    setIsListening(false);
  }, []);
  useEffect(() => {
    onListeningChange?.(isListening ? stopListening : null);
  }, [isListening, stopListening, onListeningChange]);

  const toggleMic = useCallback(() => {
    if (isListening) {
      recognitionRef.current?.stop();
      mic?.stop();
      setIsListening(false);
      return;
    }

    const SpeechRecognition = window.SpeechRecognition || window.webkitSpeechRecognition;
    if (!SpeechRecognition) {
      toast.info(t("voiceUnsupported"));
      return;
    }

    const recognition = new SpeechRecognition();
    recognition.continuous = true;
    recognition.interimResults = true;
    recognition.lang = navigator.language || "en-US";

    let finalTranscript = "";

    recognition.onresult = (event: SpeechRecognitionEvent) => {
      let interim = "";
      for (let i = event.resultIndex; i < event.results.length; i++) {
        const result = event.results[i];
        if (!result) continue;
        if (result.isFinal) {
          finalTranscript += result[0]?.transcript ?? "";
        } else {
          interim += result[0]?.transcript ?? "";
        }
      }
      setMessage(() => {
        return finalTranscript + (interim ? "\u200B" + interim : "");
      });
    };

    recognition.onend = () => {
      setIsListening(false);
      mic?.stop();
      setMessage((prev) => prev.replace(/\u200B/g, ""));
    };

    recognition.onerror = () => {
      setIsListening(false);
      mic?.stop();
      toast.error(t("speechError"));
    };

    recognitionRef.current = recognition;
    recognition.start();
    // A second capture, for the glow only. The Web Speech API analyses its own
    // audio and hands back text without ever exposing a stream, so there is
    // nothing to share; this one is read for its level and never recorded, and
    // a browser that refuses it leaves the dictation working.
    void mic?.start();
    setIsListening(true);
    finalTranscript = message;
  }, [isListening, message, mic]);

  // File upload to backend - shared by the file picker, drag-and-drop and paste.
  const uploadFiles = useCallback(
    async (files: File[], { pasted = false }: { pasted?: boolean } = {}) => {
      const accepted = files.filter((file) => {
        if (file.size <= chatMaxUploadSizeMb * 1024 * 1024) return true;
        toast.error(t("fileTooLarge", { file: file.name, max: chatMaxUploadSizeMb }));
        return false;
      });
      if (accepted.length === 0) return;

      // Every accepted file gets its card before the first request goes out, so
      // dropping four files shows four cards rather than one that moves along
      // the row. The key is a counter: two files can share a name and a size.
      const queued = accepted.map((file) => ({
        key: pendingKey.current++,
        name: file.name,
        size: file.size,
      }));
      setPending((prev) => [...prev, ...queued]);

      for (const [i, file] of accepted.entries()) {
        try {
          const result = await uploadFile(file);
          setAttachedFiles((prev) => [...prev, { file: result, pasted }]);
        } catch (err) {
          toast.error(`${file.name}: ${getErrorMessage(err, tErrors, t("uploadFailed"))}`);
        } finally {
          setPending((prev) => prev.filter((p) => p.key !== queued[i]!.key));
        }
      }
    },
    [chatMaxUploadSizeMb, t, tErrors],
  );

  const attachedIncoming = useRef<number | null>(null);
  useEffect(() => {
    if (incoming === null || attachedIncoming.current === incoming.id) return;
    attachedIncoming.current = incoming.id;
    void uploadFiles(incoming.files);
    if (incoming.text) editorRef.current?.focus();
  }, [incoming, uploadFiles]);
  // The words that came with them, once per hand-off and after whatever is
  // already typed - written during render, as state that follows a prop is.
  const [wroteIncoming, setWroteIncoming] = useState<number | null>(null);
  if (incoming?.text && wroteIncoming !== incoming.id) {
    const text = incoming.text;
    setWroteIncoming(incoming.id);
    setMessage((typed) => (typed.trim() ? `${typed.trimEnd()}\n${text}` : text));
  }

  /**
   * A pasted file or picture is attached, and a paste long enough to be a
   * document becomes one.
   *
   * A screenshot or a file copied in Finder arrives as clipboard files, which
   * the textarea ignores - Ctrl+V did nothing. They are attached as if picked.
   *
   * Pasting a wiki page into the textarea pushed the question somebody was
   * writing off the screen and left the transcript one enormous bubble. Past
   * `PASTE_AS_FILE_CHARS` it is uploaded as a `text/plain` file instead and the
   * textarea is left alone, so the question gets typed beside it.
   */
  const handlePaste = useCallback(
    (e: React.ClipboardEvent<HTMLElement>) => {
      const pastedFiles = Array.from(e.clipboardData.files);
      if (pastedFiles.length > 0) {
        e.preventDefault();
        void uploadFiles(pastedFiles);
        return;
      }
      const text = e.clipboardData.getData("text/plain");
      if (text.length <= PASTE_AS_FILE_CHARS) return;
      e.preventDefault();
      const day = new Date().toISOString().slice(0, 10);
      void uploadFiles([new File([text], `pasted-${day}.txt`, { type: "text/plain" })], {
        pasted: true,
      });
    },
    [uploadFiles],
  );

  const handleFileSelect = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      // `e.target.files` is the input's own live `FileList`, not a copy of one:
      // resetting the input empties that same object in place, so the array has
      // to be built *before* the reset. Reading it after meant `Array.from` saw
      // an empty list and the upload returned at its own empty guard - no card,
      // no toast, no request, on every pick through the picker. jsdom does not
      // reproduce the clear, so the unit suite stayed green throughout.
      const files = Array.from(e.target.files ?? []);
      // Cleared unconditionally, and before the early return: picking the same
      // file twice in a row has to fire `change` again, which is what somebody
      // does after a refusal they have since fixed.
      e.target.value = "";
      if (files.length === 0) return;
      await uploadFiles(files);
    },
    [uploadFiles],
  );

  // Anywhere on the page, not onto the composer. The strip somebody had to hit
  // was a few centimetres tall, and missing it was not a no-op - the browser's
  // default for a dropped file is to open it, so the tab left the conversation.
  // Nothing is accepted while the composer is disabled, and the overlay not
  // appearing is what says so.
  const { isDragging } = useFileDrop({
    onFiles: (files) => void uploadFiles(files),
    disabled,
  });

  const removeFile = (fileId: string) => {
    setAttachedFiles((prev) => prev.filter((a) => a.file.id !== fileId));
  };

  return (
    <form
      onSubmit={handleSubmit}
      onKeyDown={(e) => {
        // From the box or from the bar, wherever focus is while dictating.
        if (dictating && e.key === "Escape") {
          e.preventDefault();
          server?.actions.cancel();
        }
      }}
      className="relative"
    >
      <span role="status" aria-live="polite" className="sr-only">
        {announcement}
      </span>
      <FileDropOverlay
        active={isDragging}
        title={t("dropFilesAttach")}
        hint={t("dropMaxSize", { max: chatMaxUploadSizeMb })}
      />
      {mentionOpen && (
        <MentionPalette
          items={mentionMatches}
          selectedIndex={mentionIndex}
          onSelectIndex={setMentionIndex}
          onPick={pickMention}
          isLoading={offered.isLoading}
          failed={offered.isError}
          full={full ? MAX_MENTIONS : undefined}
        />
      )}
      {showPalette && (
        <SlashCommandPalette
          commands={filteredCommands}
          selectedIndex={paletteIndex}
          onSelectIndex={setPaletteIndex}
          onPick={runSlashCommand}
        />
      )}
      {(attachedFiles.length > 0 || isUploading) &&
        into(
          attachmentSlot,
          <AttachmentRow count={attachedFiles.length + pending.length}>
            {attachedFiles.map(({ file, pasted }) => (
              <AttachmentCard
                key={file.id}
                file={file}
                pasted={pasted}
                onRemove={() => removeFile(file.id)}
              />
            ))}
            {/* After the finished ones, in the order they were dropped, so a card
                does not move when its upload lands. */}
            {pending.map((p) => (
              <PendingAttachmentCard key={p.key} name={p.name} size={p.size} />
            ))}
          </AttachmentRow>,
        )}

      {replyTo && <ReplyingTo reply={replyTo} onCancel={() => setReplyTo(null)} />}

      {/* The text has the box to itself, and every control is on one row under
          it. The buttons used to sit *beside* the textarea, which is fine on
          one line and wrong on ten: the send button drifted to the vertical
          middle of a tall message, with text above it and text below. */}
      {/* Plain text with real chips in it: a picked mention and a settled
          address are drawn as what they name, and the message is still the
          one string it always was. */}
      <ComposerEditor
        ref={editorRef}
        value={message}
        mentions={mentions}
        onChange={typed}
        onKeyDown={handleKeyDown}
        onPaste={handlePaste}
        placeholder={offline ? t("reconnecting") : t("placeholder")}
        idle={
          hints && !disabled ? (
            <ComposerHints
              offered={offered.items}
              commands={allCommands.map((command) => command.name)}
            />
          ) : undefined
        }
        disabled={disabled}
        readOnly={dictating}
        // What a phone's keyboard offers: a return key that reads as a line
        // break where Enter makes one. 16px text, never less: iOS zooms the
        // page into any field smaller than that when it is focused (#2066).
        enterKeyHint={touchKeyboard() ? "enter" : "send"}
      />

      {/* `min-w-0` and a shrinkable right group: at 390px the controls used to
          run 27px past the composer's own edge, measured on an iPhone 15. */}
      {/* Inert rather than hidden while dictating: the composer does not change
          under the page's dictation pill, and the agent the recording goes to
          must not change under it either. */}
      <div className="flex items-center gap-1.5 pt-0.5 pb-1" inert={dictating}>
        <input
          ref={fileInputRef}
          type="file"
          onChange={handleFileSelect}
          accept="image/jpeg,image/png,image/gif,image/webp,image/tiff,.tiff,.tif,.txt,.md,.csv,.json,.py,.js,.ts,.tsx,.html,.css,.yaml,.yml,.toml,.xml,.sql,.sh,.pdf,.docx,.doc,.xlsx,.xlsm,.xls,.pptx,.odt,.ods,.odp,.msg,application/msword,application/vnd.ms-excel,application/vnd.openxmlformats-officedocument.presentationml.presentation,application/vnd.ms-outlook,application/vnd.oasis.opendocument.text,application/vnd.oasis.opendocument.spreadsheet,application/vnd.oasis.opendocument.presentation,application/xml"
          multiple
          className="hidden"
        />
        <ComposerSheet
          onAttach={() => fileInputRef.current?.click()}
          // The agent's engine: the browser's recogniser, or a recording sent
          // to its provider.
          onVoice={server ? startDictation : toggleMic}
          onCommand={
            slashContext
              ? () => {
                  setMessage("/");
                  editorRef.current?.focus();
                }
              : undefined
          }
          onProject={onProject}
          disabled={disabled || isUploading}
        />
        {isUploading && <Spinner className="text-muted-foreground h-4 w-4 shrink-0" />}
        {controlsSlot ? (
          <div className="flex min-w-0 items-center gap-1">{controlsSlot}</div>
        ) : null}

        <div className="ml-auto flex shrink-0 items-center gap-1">
          {actionsSlot}
          {/* Beside Send and the call, as in ChatGPT; the `+` offers it too. A
              server recording takes the box over with its own bar, so this
              button only ever starts one. */}
          <Button
            type="button"
            variant="ghost"
            size="icon"
            onClick={server ? startDictation : toggleMic}
            disabled={disabled}
            className="h-9 w-9 shrink-0"
            title={isListening ? t("stopRecording") : t("voiceInput")}
            aria-label={isListening ? t("stopRecording") : t("voiceInput")}
          >
            {isListening ? (
              <MicOff className="text-destructive h-4 w-4 animate-pulse" />
            ) : (
              <Mic className="text-muted-foreground h-4 w-4" />
            )}
          </Button>

          {canStop && onStop ? (
            <Button
              type="button"
              size="icon"
              onClick={onStop}
              disabled={stopDisabled}
              className="h-9 w-9 shrink-0 rounded-lg"
              title={t("stopGenerating")}
            >
              <span className="h-3 w-3 rounded-[3px] bg-current" aria-hidden="true" />
              <span className="sr-only">{t("stopGenerating")}</span>
            </Button>
          ) : idleSlot && !isProcessing && !message.trim() && attachedFiles.length === 0 ? (
            idleSlot
          ) : (
            <Button
              type="submit"
              size="icon"
              className="shrink-0 transition-transform active:scale-90"
              disabled={disabled || isUploading || (!message.trim() && attachedFiles.length === 0)}
            >
              {isProcessing ? <Spinner className="h-4 w-4" /> : <Send className="h-4 w-4" />}
              <span className="sr-only">{t("send")}</span>
            </Button>
          )}
        </div>
      </div>
    </form>
  );
}
