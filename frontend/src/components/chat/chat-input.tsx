"use client";

import { useState, useRef, useEffect, useCallback, useMemo } from "react";
import { getErrorMessage } from "@/lib/api-error";
import { Button, Spinner } from "@/components/ui";
import { Send, Mic, MicOff, Paperclip } from "lucide-react";
import { toast } from "sonner";
import { uploadFile, type FileUploadResponse } from "@/lib/file-api";
import { MAX_UPLOAD_SIZE_MB } from "@/lib/utils";
import { AttachmentCard, PendingAttachmentCard } from "./attachment-card";
import {
  BUILTIN_COMMANDS,
  resolveBuiltin,
  searchCommands,
  type SlashCommand,
  type SlashCommandContext,
} from "./slash-commands";
import { SlashCommandPalette } from "./slash-command-palette";
import { FileDropOverlay } from "./file-drop-overlay";
import { useChanged } from "@/hooks/use-changed";
import { useFileDrop } from "@/hooks/use-file-drop";
import { useTranslations } from "next-intl";

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
  onSend: (message: string, fileIds?: string[], files?: FileUploadResponse[]) => void;
  disabled?: boolean;
  isProcessing?: boolean;
  /** When set, a stop control replaces the send button while processing. */
  onStop?: () => void;
  /** Local actions for slash commands. Wire from <ChatContainer>. */
  slashContext?: SlashCommandContext;
  /** Effective slash commands (built-ins + user customs, after overrides). */
  commands?: SlashCommand[];
}

export function ChatInput({
  onSend,
  disabled,
  isProcessing,
  onStop,
  slashContext,
  commands,
}: ChatInputProps) {
  const tErrors = useTranslations("errors");
  const t = useTranslations("chat.input");
  const tCommands = useTranslations("chat.commands");
  const [message, setMessage] = useState("");
  const [attachedFiles, setAttachedFiles] = useState<Attachment[]>([]);
  const [pending, setPending] = useState<PendingUpload[]>([]);
  const [isListening, setIsListening] = useState(false);
  const pendingKey = useRef(0);
  const isUploading = pending.length > 0;
  // Slash-command palette state. Open while message starts with "/" and the
  // caller wired a context - without one, commands have nothing to do.
  const [paletteIndex, setPaletteIndex] = useState(0);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);
  const recognitionRef = useRef<SpeechRecognition | null>(null);

  const showPalette = !!slashContext && message.startsWith("/") && !message.includes("\n");
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
    if (!isProcessing && !isUploading && textareaRef.current) {
      textareaRef.current.focus();
    }
  }, [isProcessing, isUploading]);

  useEffect(() => {
    if (textareaRef.current) {
      textareaRef.current.style.height = "auto";
      textareaRef.current.style.height = `${Math.min(textareaRef.current.scrollHeight, 200)}px`;
    }
  }, [message]);

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
    );
    setMessage("");
    setAttachedFiles([]);
  };

  const handleKeyDown = (e: React.KeyboardEvent) => {
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
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      handleSubmit(e);
    }
  };

  const toggleMic = useCallback(() => {
    if (isListening) {
      recognitionRef.current?.stop();
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
      setMessage((prev) => prev.replace(/\u200B/g, ""));
    };

    recognition.onerror = () => {
      setIsListening(false);
      toast.error(t("speechError"));
    };

    recognitionRef.current = recognition;
    recognition.start();
    setIsListening(true);
    finalTranscript = message;
  }, [isListening, message]);

  // File upload to backend - shared by the file picker, drag-and-drop and paste.
  const uploadFiles = useCallback(
    async (files: File[], { pasted = false }: { pasted?: boolean } = {}) => {
      const accepted = files.filter((file) => {
        if (file.size <= MAX_UPLOAD_SIZE_MB * 1024 * 1024) return true;
        toast.error(t("fileTooLarge", { file: file.name, max: MAX_UPLOAD_SIZE_MB }));
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
    [t],
  );

  /**
   * A paste long enough to be a document becomes one.
   *
   * Pasting a wiki page into the textarea pushed the question somebody was
   * writing off the screen and left the transcript one enormous bubble. Past
   * `PASTE_AS_FILE_CHARS` it is uploaded as a `text/plain` file instead and the
   * textarea is left alone, so the question gets typed beside it.
   */
  const handlePaste = useCallback(
    (e: React.ClipboardEvent<HTMLTextAreaElement>) => {
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
      const files = e.target.files;
      if (!files || files.length === 0) return;
      e.target.value = "";
      await uploadFiles(Array.from(files));
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
    <form onSubmit={handleSubmit} className="relative">
      <FileDropOverlay active={isDragging} maxSizeMb={MAX_UPLOAD_SIZE_MB} />
      {showPalette && (
        <SlashCommandPalette
          commands={filteredCommands}
          selectedIndex={paletteIndex}
          onSelectIndex={setPaletteIndex}
          onPick={runSlashCommand}
        />
      )}
      {(attachedFiles.length > 0 || isUploading) && (
        <div className="flex flex-wrap items-start gap-2 pb-2">
          {attachedFiles.map(({ file, pasted }) => (
            <AttachmentCard
              key={file.id}
              file={file}
              pasted={pasted}
              onRemove={() => removeFile(file.id)}
            />
          ))}
          {pending.map((p) => (
            <PendingAttachmentCard key={p.key} name={p.name} size={p.size} />
          ))}
        </div>
      )}

      <div className="flex items-end gap-2">
        <textarea
          ref={textareaRef}
          value={message}
          onChange={(e) => setMessage(e.target.value)}
          onKeyDown={handleKeyDown}
          onPaste={handlePaste}
          placeholder={t("placeholder")}
          disabled={disabled}
          rows={1}
          className="placeholder:text-muted-foreground min-h-[40px] flex-1 resize-none scrollbar-thin bg-transparent py-2.5 text-sm focus:outline-none disabled:cursor-not-allowed disabled:opacity-50 sm:text-base"
        />

        <div className="flex shrink-0 items-center gap-0.5 pb-1">
          <Button
            type="button"
            variant="ghost"
            size="icon"
            onClick={toggleMic}
            disabled={disabled}
            className="h-9 w-9"
            title={isListening ? t("stopRecording") : t("voiceInput")}
            aria-label={isListening ? t("stopRecording") : t("voiceInput")}
          >
            {isListening ? (
              <MicOff className="text-destructive h-4 w-4 animate-pulse" />
            ) : (
              <Mic className="text-muted-foreground h-4 w-4" />
            )}
          </Button>

          <Button
            type="button"
            variant="ghost"
            size="icon"
            onClick={() => fileInputRef.current?.click()}
            disabled={disabled || isUploading}
            className="h-9 w-9"
            title={t("attachFile")}
            aria-label={t("attachFile")}
          >
            {isUploading ? (
              <Spinner className="text-muted-foreground h-4 w-4" />
            ) : (
              <Paperclip className="text-muted-foreground h-4 w-4" />
            )}
          </Button>
          <input
            ref={fileInputRef}
            type="file"
            onChange={handleFileSelect}
            accept="image/jpeg,image/png,image/gif,image/webp,.txt,.md,.csv,.json,.py,.js,.ts,.tsx,.html,.css,.yaml,.yml,.toml,.xml,.sql,.sh,.pdf,.docx,.xlsx,.xlsm"
            multiple
            className="hidden"
          />

          {isProcessing && onStop ? (
            <Button
              type="button"
              size="icon"
              onClick={onStop}
              className="h-9 w-9 rounded-lg"
              title={t("stopGenerating")}
            >
              <span className="h-3 w-3 rounded-[3px] bg-current" aria-hidden="true" />
              <span className="sr-only">{t("stopGenerating")}</span>
            </Button>
          ) : (
            <Button
              type="submit"
              size="icon"
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
