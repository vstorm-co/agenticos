"use client";

import { useId } from "react";
import { useTranslations } from "next-intl";

import type { ChatSendMode } from "@/lib/chat-send-mode";

export type ChatSendModeUnavailableReason = "context" | "disconnected";

export function ChatSendModeControl({
  value,
  onChange,
  unavailableReason,
}: {
  value: ChatSendMode;
  onChange: (mode: ChatSendMode) => void;
  unavailableReason?: ChatSendModeUnavailableReason;
}) {
  const t = useTranslations("chat.sendMode");
  const id = useId();
  const hint = unavailableReason
    ? t(unavailableReason === "disconnected" ? "steerDisconnected" : "steerUnavailable")
    : t(value === "steer" ? "steerDescription" : "queueDescription");

  return (
    <fieldset
      aria-describedby={`${id}-hint`}
      className="flex min-w-0 flex-wrap items-center gap-x-2 gap-y-1 text-xs"
      data-tour="chat-send-mode"
    >
      <legend className="sr-only">{t("label")}</legend>
      <label className="inline-flex shrink-0 items-center gap-1.5">
        <input
          type="radio"
          name={id}
          value="queue"
          checked={value === "queue"}
          onChange={() => onChange("queue")}
          className="accent-primary size-3.5 shrink-0"
        />
        <span>{t("queue")}</span>
      </label>
      <label className="inline-flex shrink-0 items-center gap-1.5">
        <input
          type="radio"
          name={id}
          value="steer"
          checked={value === "steer"}
          onChange={() => onChange("steer")}
          disabled={unavailableReason !== undefined}
          className="accent-primary size-3.5 shrink-0"
        />
        <span className={unavailableReason ? "text-muted-foreground" : undefined}>
          {t("steer")}
        </span>
      </label>
      <p
        id={`${id}-hint`}
        className="text-muted-foreground min-w-0 basis-full text-[10px] leading-4"
      >
        {hint}
      </p>
    </fieldset>
  );
}
