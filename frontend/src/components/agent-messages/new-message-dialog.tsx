"use client";

import { useMemo, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { toast } from "sonner";
import { Paperclip, X } from "lucide-react";

import {
  Button,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Input,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Textarea,
} from "@/components/ui";
import { useAgentMessageRecipients, useSendAgentMessage } from "@/hooks";
import { useAgents } from "@/hooks/use-agents";
import { getErrorMessage } from "@/lib/api-error";
import { MAX_ATTACHMENTS, MAX_MESSAGE_CHARS } from "@/lib/agent-messages-api";
import { uploadFile } from "@/lib/file-api";
import { DIALOG_BODY, DIALOG_COLUMN, DIALOG_FORM } from "@/lib/dialog-sizes";
import { cn } from "@/lib/utils";
import type { AgentRef } from "@/types/agent-messages";

interface NewMessageDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSent?: (threadId: string) => void;
}

/**
 * Start a thread: which of the caller's runnable agents sends, which agent
 * it goes to, what it says, and up to ten files already uploaded.
 *
 * The recipient list is the backend's own — the agents this caller may
 * message — searched here by slug or name. Sending needs the caller to be
 * able to run both agents; the backend enforces that, so a refusal here is
 * toasted with its own words rather than hidden by filtering.
 */
export function NewMessageDialog({ open, onOpenChange, onSent }: NewMessageDialogProps) {
  const t = useTranslations("agentMessages");
  const tErrors = useTranslations("errors");
  const { send } = useSendAgentMessage();
  const {
    recipients,
    isLoading: isLoadingRecipients,
    error: recipientsError,
  } = useAgentMessageRecipients();
  const { agents, error: agentsError } = useAgents();

  const [senderId, setSenderId] = useState<string | null>(null);
  const [recipientId, setRecipientId] = useState<string | null>(null);
  const [query, setQuery] = useState("");
  const [body, setBody] = useState("");
  const [files, setFiles] = useState<File[]>([]);
  const [uploading, setUploading] = useState(false);
  const fileInput = useRef<HTMLInputElement>(null);

  // The sender is an agent the caller may run — the chat picker's list. If
  // that list itself was refused, the recipients stand in — they are the
  // published agents among the same set — and the backend still refuses
  // honestly if one of them cannot send.
  const runnable = useMemo(() => agents.filter((agent) => agent.can_run), [agents]);
  const senderOptions: AgentRef[] = runnable.length > 0 ? runnable : agentsError ? recipients : [];
  const sender = senderId ?? senderOptions[0]?.id ?? null;

  const filtered = useMemo(() => {
    const needle = query.trim().toLowerCase();
    if (needle === "") return recipients;
    return recipients.filter(
      (agent) =>
        agent.slug.toLowerCase().includes(needle) || agent.name.toLowerCase().includes(needle),
    );
  }, [recipients, query]);

  const addFiles = (next: File[]) => {
    const combined = [...files, ...next].slice(0, MAX_ATTACHMENTS);
    if (combined.length < files.length + next.length) {
      toast.error(t("tooManyFiles", { max: MAX_ATTACHMENTS }));
    }
    setFiles(combined);
  };

  const reset = () => {
    setSenderId(null);
    setRecipientId(null);
    setQuery("");
    setBody("");
    setFiles([]);
  };

  const handleSend = async () => {
    if (sender === null || recipientId === null || body.trim() === "") return;
    setUploading(true);
    const attachmentFileIds: string[] = [];
    try {
      for (const file of files) {
        const uploaded = await uploadFile(file);
        attachmentFileIds.push(uploaded.id);
      }
    } catch (error) {
      // An upload failed: nothing was sent, and the message is still here
      // to try again.
      setUploading(false);
      toast.error(getErrorMessage(error, tErrors, t("uploadFailed")));
      return;
    }
    setUploading(false);
    try {
      const message = await send.mutateAsync({
        sender_agent_id: sender,
        recipient: recipientId,
        body: body.trim(),
        attachment_file_ids: attachmentFileIds,
      });
      reset();
      onOpenChange(false);
      onSent?.(message.thread_id);
    } catch {
      // The send hook already toasted the refusal with the backend's words.
    }
  };

  const busy = uploading || send.isPending;
  const canSend = sender !== null && recipientId !== null && body.trim() !== "" && !busy;

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next) reset();
        onOpenChange(next);
      }}
    >
      <DialogContent className={cn(DIALOG_COLUMN, DIALOG_FORM)}>
        <DialogHeader>
          <DialogTitle>{t("newMessageTitle")}</DialogTitle>
          <DialogDescription>{t("newMessageDescription")}</DialogDescription>
        </DialogHeader>

        <div className={cn(DIALOG_BODY, "space-y-4")}>
          <div className="space-y-1.5" data-tour="agent-message-dialog-sender">
            <Label htmlFor="agent-message-sender">{t("senderLabel")}</Label>
            {senderOptions.length === 0 ? (
              <p className="text-muted-foreground text-sm">{t("noRunnableAgent")}</p>
            ) : (
              <Select value={sender ?? undefined} onValueChange={setSenderId}>
                <SelectTrigger id="agent-message-sender" className="w-full">
                  <SelectValue placeholder={t("chooseSender")} />
                </SelectTrigger>
                <SelectContent>
                  {senderOptions.map((agent) => (
                    <SelectItem key={agent.id} value={agent.id}>
                      <span>{agent.name}</span>{" "}
                      <span className="text-muted-foreground">{`@${agent.slug}`}</span>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            )}
          </div>

          <div className="space-y-1.5" data-tour="agent-message-dialog-recipient">
            <Label htmlFor="agent-message-recipient-search">{t("recipientLabel")}</Label>
            <Input
              id="agent-message-recipient-search"
              value={query}
              onChange={(event) => setQuery(event.target.value)}
              placeholder={t("searchRecipients")}
            />
            {recipientsError ? (
              <p className="text-muted-foreground text-sm">{recipientsError}</p>
            ) : isLoadingRecipients ? (
              <p className="text-muted-foreground text-sm">{t("loadingRecipients")}</p>
            ) : filtered.length === 0 ? (
              <p className="text-muted-foreground text-sm">{t("noRecipients")}</p>
            ) : (
              <div
                role="listbox"
                aria-label={t("recipientLabel")}
                className="border-border max-h-48 overflow-y-auto rounded-md border"
              >
                {filtered.map((agent) => {
                  const selected = agent.id === recipientId;
                  return (
                    <button
                      key={agent.id}
                      type="button"
                      role="option"
                      aria-selected={selected}
                      onClick={() => setRecipientId(agent.id)}
                      className={cn(
                        "hover:bg-muted/60 flex w-full items-center gap-2 px-3 py-2 text-left text-sm",
                        selected && "bg-muted/60 font-medium",
                      )}
                    >
                      <span>{agent.name}</span>
                      <span className="text-muted-foreground">{`@${agent.slug}`}</span>
                    </button>
                  );
                })}
              </div>
            )}
          </div>

          <div className="space-y-1.5" data-tour="agent-message-dialog-body">
            <Label htmlFor="agent-message-body">{t("bodyLabel")}</Label>
            <Textarea
              id="agent-message-body"
              value={body}
              onChange={(event) => setBody(event.target.value.slice(0, MAX_MESSAGE_CHARS))}
              placeholder={t("messagePlaceholder")}
              rows={5}
            />
            <p className="text-muted-foreground text-right text-xs">
              {t("charCount", { count: body.length, max: MAX_MESSAGE_CHARS })}
            </p>
          </div>

          <div className="space-y-1.5">
            <input
              ref={fileInput}
              type="file"
              multiple
              className="hidden"
              aria-label={t("attachFiles")}
              onChange={(event) => {
                addFiles(Array.from(event.target.files ?? []));
                event.target.value = "";
              }}
            />
            <Button
              type="button"
              variant="outline"
              size="sm"
              disabled={files.length >= MAX_ATTACHMENTS}
              onClick={() => fileInput.current?.click()}
            >
              <Paperclip className="size-4" aria-hidden />
              {t("attachFiles")}
            </Button>
            {files.length > 0 ? (
              <ul className="space-y-1">
                {files.map((file) => (
                  <li key={`${file.name}-${file.size}`} className="flex items-center gap-2 text-sm">
                    <span className="min-w-0 flex-1 truncate">{file.name}</span>
                    <button
                      type="button"
                      aria-label={t("removeFile", { name: file.name })}
                      onClick={() => setFiles((current) => current.filter((item) => item !== file))}
                      className="text-muted-foreground hover:text-foreground shrink-0"
                    >
                      <X className="size-3.5" aria-hidden />
                    </button>
                  </li>
                ))}
              </ul>
            ) : null}
          </div>
        </div>

        <DialogFooter>
          <Button type="button" variant="outline" onClick={() => onOpenChange(false)}>
            {t("cancel")}
          </Button>
          <Button
            type="button"
            data-tour="agent-message-dialog-send"
            disabled={!canSend}
            onClick={() => void handleSend()}
          >
            {t("send")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
