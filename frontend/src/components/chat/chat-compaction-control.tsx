"use client";

import { Shrink } from "lucide-react";
import { useTranslations } from "next-intl";

import { Button } from "@/components/ui/button";
import type { ChatCompactionStatus } from "@/types/chat";

/** A deliberate maintenance action; it never submits a chat message. */
export function ChatCompactionControl({
  available,
  status,
  disabled = false,
  onCompact,
}: {
  available: boolean;
  status: ChatCompactionStatus;
  disabled?: boolean;
  onCompact: () => boolean;
}) {
  const t = useTranslations("chat.manualCompaction");
  const running = status === "running";
  if (!available && !running) return null;

  return (
    <Button
      type="button"
      variant="ghost"
      size="icon-sm"
      data-tour="chat-compact-now"
      aria-label={t("action")}
      title={disabled ? t("busyHint") : t("description")}
      disabled={disabled || !available}
      loading={running}
      onClick={onCompact}
    >
      <Shrink aria-hidden />
    </Button>
  );
}

/** The maintenance result belongs beside the composer, outside the transcript. */
export function ChatCompactionNotice({
  status,
  messagesBefore,
}: {
  status: ChatCompactionStatus;
  messagesBefore?: number | null;
}) {
  const t = useTranslations("chat.manualCompaction");
  if (status === "idle") return null;
  const failed = status === "failed" || status === "busy" || status === "unavailable";
  const label =
    status === "running" && messagesBefore != null
      ? t("runningCount", { count: messagesBefore })
      : t(status);

  return (
    <p role={failed ? "alert" : "status"} className="text-muted-foreground mb-2 px-1 text-xs">
      {label}
    </p>
  );
}
