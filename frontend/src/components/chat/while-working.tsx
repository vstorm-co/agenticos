"use client";

import { CornerDownRight, Loader2, MessageCircleQuestion, X } from "lucide-react";
import { useTranslations } from "next-intl";

import { MarkdownContent } from "@/components/chat/markdown-content";
import type { SendMode, SideQuestion, SteerDraft } from "@/hooks/use-chat";
import { cn } from "@/lib/utils";

const MODES: readonly SendMode[] = ["steer", "after", "aside"];

/**
 * What a message typed while the agent works does (#2087).
 *
 * Joining the task is the default: a correction is most useful while the agent
 * can still act on it. Waiting for the turn and asking on the side are the two
 * other things a person means, offered beside it rather than behind a menu.
 */
export function SendModePicker({
  mode,
  onChange,
}: {
  mode: SendMode;
  onChange: (mode: SendMode) => void;
}) {
  const t = useTranslations("chat.whileWorking");
  return (
    <div
      role="radiogroup"
      aria-label={t("label")}
      className="bg-foreground/[0.04] mb-2 inline-flex rounded-full p-0.5 text-xs"
    >
      {MODES.map((option) => (
        <button
          key={option}
          type="button"
          role="radio"
          aria-checked={mode === option}
          onClick={() => onChange(option)}
          className={cn(
            "rounded-full px-3 py-1 font-medium transition-colors",
            mode === option
              ? "bg-background text-foreground shadow-sm"
              : "text-muted-foreground hover:text-foreground",
          )}
        >
          {t(`modes.${option}`)}
        </button>
      ))}
    </div>
  );
}

/** Corrections on their way to the running turn, until the model has them. */
export function WaitingSteers({ steers }: { steers: SteerDraft[] }) {
  const t = useTranslations("chat.whileWorking");
  if (steers.length === 0) return null;
  return (
    <div className="border-border bg-card mb-2 rounded-2xl border px-3 py-2">
      <p className="text-muted-foreground mb-1.5 flex items-center gap-1.5 text-xs">
        <Loader2 className="h-3 w-3 animate-spin" aria-hidden />
        {t("steersWaiting")}
      </p>
      <ul className="space-y-1">
        {steers.map((steer) => (
          <li key={steer.id} className="flex items-start gap-2 text-sm">
            <CornerDownRight className="text-muted-foreground mt-0.5 h-3.5 w-3.5 shrink-0" />
            <span className="line-clamp-2 break-words">{steer.text}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

/** Questions asked beside the running turn, each with its answer once it comes. */
export function SideAnswers({
  asides,
  onDismiss,
}: {
  asides: SideQuestion[];
  onDismiss: (id: string) => void;
}) {
  const t = useTranslations("chat.whileWorking");
  if (asides.length === 0) return null;
  return (
    <ul className="mb-2 space-y-2">
      {asides.map((aside) => (
        <li key={aside.id} className="border-border bg-card rounded-2xl border px-3 py-2.5">
          <div className="mb-1 flex items-start gap-2">
            <MessageCircleQuestion className="text-muted-foreground mt-0.5 h-3.5 w-3.5 shrink-0" />
            <p className="text-muted-foreground flex min-w-0 flex-1 flex-wrap gap-x-1 text-xs">
              <span className="text-foreground/70 font-medium">{t("askedAside")}</span>
              <span className="break-words">{aside.question}</span>
            </p>
            <button
              type="button"
              onClick={() => onDismiss(aside.id)}
              aria-label={t("dismiss")}
              title={t("dismiss")}
              className="text-muted-foreground hover:text-foreground hover:bg-foreground/10 -mt-0.5 rounded-md p-1"
            >
              <X className="h-3.5 w-3.5" />
            </button>
          </div>
          {aside.error ? (
            <p className="text-destructive text-sm">{aside.error}</p>
          ) : aside.answer !== undefined ? (
            <div className="text-sm">
              <MarkdownContent content={aside.answer} />
            </div>
          ) : (
            <p className="text-muted-foreground flex items-center gap-1.5 text-sm">
              <Loader2 className="h-3.5 w-3.5 animate-spin" aria-hidden />
              {t("answering")}
            </p>
          )}
        </li>
      ))}
    </ul>
  );
}
